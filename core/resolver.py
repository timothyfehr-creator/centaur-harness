"""Contested-logistics resolver + reducer (WP-E1).

Pure deterministic transition logic for the abstract slice, implementing the TOTAL
resolution table in docs/ENGINE_CONTRACT.md. No I/O, no commit/durability (that is the
commit machinery, a separate module). Only the resolver reads the hidden block_threshold;
``reduce()`` needs the events alone and is the SOLE constructor of the next state.
"""
from __future__ import annotations

import copy

from canon import canonical_bytes
from rng import draw as rng_draw
from rng import draw_address

RESOLVER_ID = "contested_logistics"
RESOLVER_VERSION = "1"
RULESET_VERSION = "1"
# Event types that are STOCHASTIC terminals (each references exactly one consumed draw). The turn-replay
# gate reads this per-resolver for its draw->event coherence check.
STOCHASTIC_TERMINALS = ("SUPPLY_DELIVERED", "SUPPLY_LOST")

ACTORS = ("BLUE", "RED")
# Role/action capability: each actor commands exactly one action type (BLUE supplies, RED
# interdicts). A command whose actor/action pairing is absent here is REJECTED — it would
# otherwise validate, then go INERT in resolve() (which acts only on a BLUE DISPATCH_SUPPLY and a
# RED BLOCK_ROUTE). Closes the "legal-but-inert" trapdoor (independent red-team finding §1).
ACTION_BY_ACTOR = {"BLUE": "DISPATCH_SUPPLY", "RED": "BLOCK_ROUTE"}
ROUTES = ("r1", "r2")
BLOCKABLE_WITH_THRESHOLD = ("r1",)  # r2 is unblockable (no route_secret)
MIN_QTY, MAX_QTY = 1, 30


class ResolveError(ValueError):
    """A malformed event batch reached reduce() (grammar/conservation violation)."""


# --- typed-state helpers -------------------------------------------------------------

def _fields(state: dict, entity_id: str) -> dict:
    for ent in state["state"]["entities"]:
        if ent["id"] == entity_id:
            return ent["fields"]
    raise ResolveError(f"missing entity {entity_id!r}")

def _block_threshold(state: dict) -> int:
    return _fields(state, "route_secret:r1")["block_threshold"]["value"]

def conservation_total(state: dict) -> int:
    bs = _fields(state, "blue_supply")
    return sum(bs[k]["value"] for k in ("origin", "in_transit", "delivered", "loss_sink"))

def is_non_negative(state: dict) -> bool:
    bs = _fields(state, "blue_supply")
    return all(bs[k]["value"] >= 0 for k in ("origin", "in_transit", "delivered", "loss_sink"))

def _remaining_origin(state: dict) -> int | None:
    """BLUE's remaining dispatchable supply, or None if the state lacks it (then the supply check is skipped
    and reduce()'s is_non_negative invariant is the backstop)."""
    try:
        origin = _fields(state, "blue_supply")["origin"]["value"]
    except (ResolveError, KeyError, TypeError):
        return None
    return origin if isinstance(origin, int) and not isinstance(origin, bool) else None


# --- validate_all: deterministic legality, ZERO mutation, reject-all-or-resolve ------

def validate_all(commands: list, start_state: dict, ruleset: object = None):
    """Return ``(accepted, rejections)``. If rejections is non-empty the turn is rejected
    (accepted == [] — no partial application)."""
    rejections: list[tuple[str, str]] = []
    seen_actor: dict[str, int] = {}
    for i, cmd in enumerate(commands):
        actor = cmd.get("actor_id")
        action = cmd.get("action_type")
        params = cmd.get("params", {})
        if actor not in ACTORS:
            rejections.append(("unknown-actor", f"actor_id {actor!r} not in {ACTORS}"))
        elif action in ("DISPATCH_SUPPLY", "BLOCK_ROUTE") and ACTION_BY_ACTOR[actor] != action:
            rejections.append(
                ("role-action-mismatch",
                 f"actor {actor!r} may not issue {action!r} (only {ACTION_BY_ACTOR[actor]!r})"))
        if actor in seen_actor:
            rejections.append(("too-many-commands", f"actor {actor!r} has more than one command"))
        else:
            seen_actor[actor] = i
        if action == "DISPATCH_SUPPLY":
            qty = params.get("quantity")
            if isinstance(qty, bool) or not isinstance(qty, int) or not (MIN_QTY <= qty <= MAX_QTY):
                rejections.append(("out-of-range", f"quantity {qty!r} not in [{MIN_QTY},{MAX_QTY}]"))
            elif (origin := _remaining_origin(start_state)) is not None and qty > origin:
                # can't dispatch more supply than remains (else reduce drives origin negative -> a crash);
                # this makes legality STATE-DEPENDENT, so command_legality must be re-run on the same state.
                rejections.append(("insufficient-supply", f"quantity {qty} > remaining origin {origin}"))
            if params.get("route") not in ROUTES:
                rejections.append(("unknown-route", f"route {params.get('route')!r}"))
        elif action == "BLOCK_ROUTE":
            if params.get("route") not in ROUTES:
                rejections.append(("unknown-route", f"route {params.get('route')!r}"))
        else:
            rejections.append(("invalid-enum", f"action_type {action!r}"))
    accepted = [] if rejections else list(commands)
    return accepted, rejections


# The legality reject codes validate_all can emit -- the VALUE-legality + role/actor namespace, DISTINCT from
# command_extractor's well-formedness REJECT_CODES. Sourced here so the agent layer (the drive + the
# provenance gate) can recognize + RE-VERIFY an engine-illegal-but-well-formed command without re-implementing
# the rules.
LEGALITY_REJECT_CODES = (
    "unknown-actor", "role-action-mismatch", "too-many-commands",
    "out-of-range", "unknown-route", "invalid-enum", "insufficient-supply",
)


def command_legality(command: dict, start_state: dict, ruleset: object = None) -> str | None:
    """The FIRST legality reject code for ONE harness-bound command (its actor_id included), or None if legal.
    Reuses validate_all (the single legality authority) on a one-command batch -- so the drive can forfeit just
    an illegal mover and the gate can RE-VERIFY the illegality, neither forking the rules. (`too-many-commands`
    is a cross-command code a single-command batch cannot raise.)"""
    _, rejections = validate_all([command], start_state, ruleset)
    return rejections[0][0] if rejections else None


def sort_commands(accepted: list) -> list:
    """Total order: lexicographic over each command's canon-v1 bytes (file order irrelevant)."""
    return sorted(accepted, key=canonical_bytes)


# --- resolve: the TOTAL table -> ordered events (+ draw records) ---------------------

def _by_actor(accepted: list, actor: str):
    return next((c for c in accepted if c.get("actor_id") == actor), None)

def resolve(accepted: list, *, block_threshold: int, master_seed: int, turn: int = 0):
    """Map an accepted batch to an ordered event batch + draw records, per the table.
    A d100 is consumed iff a block targets a DISPATCHED route that has a threshold (only r1)."""
    blue = _by_actor(accepted, "BLUE")
    red = _by_actor(accepted, "RED")
    events: list[dict] = []
    draws: list[dict] = []

    dispatched_route = None
    dispatch_qty = None
    if blue is not None and blue["action_type"] == "DISPATCH_SUPPLY":
        dispatched_route = blue["params"]["route"]
        dispatch_qty = blue["params"]["quantity"]
        events.append({
            "event_id": f"ev-{len(events) + 1:03d}", "turn": turn,
            "event_type": "SUPPLY_DISPATCHED", "route_id": dispatched_route,
            "quantity": dispatch_qty, "source_command_id": blue["command_id"],
        })

    blocked_route = None
    if red is not None and red["action_type"] == "BLOCK_ROUTE":
        blocked_route = red["params"]["route"]
        events.append({
            "event_id": f"ev-{len(events) + 1:03d}", "turn": turn,
            "event_type": "ROUTE_BLOCK_ATTEMPTED", "route_id": blocked_route,
            "source_command_id": red["command_id"],
        })

    if dispatched_route is not None:
        contested = (blocked_route == dispatched_route) and (dispatched_route in BLOCKABLE_WITH_THRESHOLD)
        lost = False
        terminal = {
            "event_id": f"ev-{len(events) + 1:03d}", "turn": turn,
            "event_type": None, "route_id": dispatched_route, "quantity": dispatch_qty,
        }
        if contested:
            address = draw_address(
                turn=turn, phase="resolve", actor_id="RED", action_type="BLOCK_ROUTE",
                target_route=dispatched_route, draw_name="block_resolve", draw_index=0,
                resolver_id=RESOLVER_ID,
            )
            d = rng_draw(master_seed, address)
            draws.append({
                "draw_id": "draw-001", "address": address, "raw_uint": d["raw_uint"],
                "d100": d["d100"], "consuming_rule_id": "block-resolve",
            })
            lost = d["d100"] < block_threshold   # block SUCCEEDS iff d100 < threshold
            terminal["draw_ref"] = "draw-001"
        terminal["event_type"] = "SUPPLY_LOST" if lost else "SUPPLY_DELIVERED"
        events.append(terminal)

    return events, draws


# --- reduce: the SOLE state constructor (rejects malformed batches) ------------------

def reduce(start_state: dict, events: list) -> dict:
    """new_state := reduce(start_state, event_batch). Needs only the events; never the
    threshold or the draw. Rejects route/quantity mismatch, duplicate/orphan terminals."""
    state = copy.deepcopy(start_state)
    bs = _fields(state, "blue_supply")
    dispatch: tuple | None = None
    terminal_seen = False
    for ev in events:
        kind = ev.get("event_type")
        if kind == "SUPPLY_DISPATCHED":
            if dispatch is not None:
                raise ResolveError("duplicate-dispatch")
            dispatch = (ev["route_id"], ev["quantity"])
            bs["origin"]["value"] -= ev["quantity"]
            bs["in_transit"]["value"] += ev["quantity"]
        elif kind in ("SUPPLY_DELIVERED", "SUPPLY_LOST"):
            if dispatch is None:
                raise ResolveError("illegal-order")          # terminal before any dispatch
            if terminal_seen:
                raise ResolveError("duplicate-terminal")
            if ev["route_id"] != dispatch[0]:
                raise ResolveError("route-mismatch")
            if ev["quantity"] != dispatch[1]:
                raise ResolveError("quantity-mismatch")
            terminal_seen = True
            bs["in_transit"]["value"] -= ev["quantity"]
            sink = "delivered" if kind == "SUPPLY_DELIVERED" else "loss_sink"
            bs[sink]["value"] += ev["quantity"]
        elif kind == "ROUTE_BLOCK_ATTEMPTED":
            pass
        else:
            raise ResolveError(f"unknown-event-type {kind!r}")
    return state


# --- transition: the pure phase machine (NO commit/durability — that is separate) ----

def transition(start_state: dict, commands: list, *, master_seed: int, turn: int = 0,
               ruleset: object = None) -> dict:
    """validate_all -> sort -> resolve -> reduce -> invariant check. Returns a result dict;
    does NOT persist. A rejection leaves the state unchanged and commits nothing."""
    accepted, rejections = validate_all(commands, start_state, ruleset)
    if rejections:
        return {"status": "rejected", "rejections": rejections,
                "events": [], "draws": [], "resulting_state": start_state}
    ordered = sort_commands(accepted)
    events, draws = resolve(
        ordered, block_threshold=_block_threshold(start_state),
        master_seed=master_seed, turn=turn,
    )
    new_state = reduce(start_state, events)
    if conservation_total(new_state) != conservation_total(start_state) or not is_non_negative(new_state):
        raise ResolveError("invariant-violation")  # never commit an invariant-violating turn
    return {"status": "resolved", "events": events, "draws": draws, "resulting_state": new_state}

"""Contested-logistics resolver + reducer (WP-E1).

Pure deterministic transition logic for the abstract slice, implementing the TOTAL
resolution table in docs/ENGINE_CONTRACT.md. No I/O, no commit/durability (that is the
commit machinery, a separate module). Only the resolver reads the hidden block_threshold;
``reduce()`` needs the events alone and is the SOLE constructor of the next state.
"""
from __future__ import annotations

import copy

from canon import canonical_bytes
from rng import draw as rng_draw, draw_address

RESOLVER_ID = "contested_logistics"
RESOLVER_VERSION = "1"
RULESET_VERSION = "1"
# Event types that are STOCHASTIC terminals (each references exactly one consumed draw). The turn-replay
# gate reads this per-resolver for its draw->event coherence check.
STOCHASTIC_TERMINALS = ("SUPPLY_DELIVERED", "SUPPLY_LOST")

ACTORS = ("BLUE", "RED")
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


# --- validate_all: deterministic legality, ZERO mutation, reject-all-or-resolve ------

def validate_all(commands: list, start_state: dict, ruleset: object = None):
    """Return ``(accepted, rejections)``. If rejections is non-empty the turn is rejected
    (accepted == [] — no partial application)."""
    rejections: list[tuple[str, str]] = []
    seen_actor: dict[str, int] = {}
    for i, cmd in enumerate(commands):
        actor = cmd.get("actor_id")
        if actor in seen_actor:
            rejections.append(("too-many-commands", f"actor {actor!r} has more than one command"))
        else:
            seen_actor[actor] = i
        action = cmd.get("action_type")
        params = cmd.get("params", {})
        if action == "DISPATCH_SUPPLY":
            qty = params.get("quantity")
            if isinstance(qty, bool) or not isinstance(qty, int) or not (MIN_QTY <= qty <= MAX_QTY):
                rejections.append(("out-of-range", f"quantity {qty!r} not in [{MIN_QTY},{MAX_QTY}]"))
            if params.get("route") not in ROUTES:
                rejections.append(("unknown-route", f"route {params.get('route')!r}"))
        elif action == "BLOCK_ROUTE":
            if params.get("route") not in ROUTES:
                rejections.append(("unknown-route", f"route {params.get('route')!r}"))
        else:
            rejections.append(("invalid-enum", f"action_type {action!r}"))
    accepted = [] if rejections else list(commands)
    return accepted, rejections


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

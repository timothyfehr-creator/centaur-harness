"""Turn-advancing contested-logistics resolver (WP-A1a) — the command-accepting engine the offline
agent substrate plays.

Identical game logic to ``core.resolver`` (BLUE dispatches, RED interdicts, one contested d100), but each
turn additionally emits a terminal ``TURN_ADVANCED`` event and advances ``state.as_of_turn`` — the
per-turn lineage the multi-turn replay chain check requires (``resulting_state.as_of_turn ==
start_state.as_of_turn + 1``; see ``validate_turn_replay.check_chain``). The shipped ``contested_logistics``
resolver and its committed golden vectors are left BYTE-UNTOUCHED; this is a separate ``resolver_id`` so it
can drive multi-turn agent campaigns without regenerating them.

Interface plugged into ``turn_record.assemble`` / ``validate_turn_replay``: {RESOLVER_ID, RESOLVER_VERSION,
RULESET_VERSION, STOCHASTIC_TERMINALS, validate_all, sort_commands, transition, reduce}.
"""
from __future__ import annotations

import resolver as base
from resolver import (  # unchanged legality + ordering surface
    LEGALITY_REJECT_CODES,
    ResolveError,
    command_legality,
    sort_commands,
    validate_all,
)

RESOLVER_ID = "agent_logistics"
RESOLVER_VERSION = "1"
RULESET_VERSION = base.RULESET_VERSION
STOCHASTIC_TERMINALS = base.STOCHASTIC_TERMINALS  # ("SUPPLY_DELIVERED", "SUPPLY_LOST") — drawn terminals

__all__ = ["RESOLVER_ID", "RESOLVER_VERSION", "RULESET_VERSION", "STOCHASTIC_TERMINALS",
           "validate_all", "command_legality", "LEGALITY_REJECT_CODES", "sort_commands",
           "resolve", "reduce", "transition", "ResolveError"]


def resolve(accepted: list, *, block_threshold: int, master_seed: int, turn: int = 0):
    """base.resolve + one terminal TURN_ADVANCED event (``to_turn == turn + 1``).

    NOTE: the contested d100's draw ADDRESS embeds ``resolver_id="contested_logistics"`` (base.resolve
    hardcodes its own id) — this is REQUIRED for the byte-identical-supply contract (a different
    resolver_id in the address would change the drawn d100). It round-trips cleanly under the replay
    gate (recompute dispatches by the record's resolver_id, then base.resolve regenerates the same
    address), so a committed agent_logistics draw address self-identifies as ``contested_logistics`` by
    design, not by accident.
    """
    events, draws = base.resolve(accepted, block_threshold=block_threshold,
                                 master_seed=master_seed, turn=turn)
    events.append({"event_id": f"ev-{len(events) + 1:03d}", "turn": turn,
                   "event_type": "TURN_ADVANCED", "to_turn": turn + 1})
    return events, draws


def reduce(start_state: dict, events: list) -> dict:
    """base.reduce over the supply events + TURN_ADVANCED advancing ``as_of_turn`` (the SOLE constructor)."""
    supply_events = [e for e in events if e.get("event_type") != "TURN_ADVANCED"]
    new_state = base.reduce(start_state, supply_events)   # fresh deepcopy; entities mutated; as_of_turn untouched
    for ev in events:
        if ev.get("event_type") == "TURN_ADVANCED":
            new_state["state"]["as_of_turn"] = ev["to_turn"]
    return new_state


def transition(start_state: dict, commands: list, *, master_seed: int, turn: int = 0,
               ruleset: object = None) -> dict:
    """validate -> sort -> resolve(+TURN_ADVANCED) -> reduce(+as_of_turn) -> invariant + turn-advance check."""
    accepted, rejections = validate_all(commands, start_state, ruleset)
    if rejections:
        return {"status": "rejected", "rejections": rejections,
                "events": [], "draws": [], "resulting_state": start_state}
    ordered = sort_commands(accepted)
    events, draws = resolve(ordered, block_threshold=base._block_threshold(start_state),
                            master_seed=master_seed, turn=turn)
    new_state = reduce(start_state, events)
    if base.conservation_total(new_state) != base.conservation_total(start_state) \
            or not base.is_non_negative(new_state):
        raise ResolveError("invariant-violation")    # never commit an invariant-violating turn
    advances = [e for e in events if e["event_type"] == "TURN_ADVANCED"]
    if len(advances) != 1 or advances[0]["to_turn"] != start_state["state"]["as_of_turn"] + 1:
        raise ResolveError("turn-advance-violation")
    return {"status": "resolved", "events": events, "draws": draws, "resulting_state": new_state}

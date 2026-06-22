"""Typed-state + event projector (WP-E1 fog) — the sibling of context_compiler for typed state.

Projects the adjudicator's authoritative turn record to a per-agent view:
- STATE: public typed entities only — never a ROUTE_SECRET (the hidden block_threshold), and never
  the full-state ``state_digest``.
- EVENTS: the agent's own + observable-terminal events — never an opponent's ROUTE_BLOCK_ATTEMPTED
  (so a *failed* block does not leak the opponent's action), and stripped of adjudicator-only
  provenance (raw draws, draw_ref, source_command_id, master_seed).
- DIGEST: a digest over the agent's OWN projection only — never the full-state or any adjudicator-only
  digest, seed, or count.

Reuses the load_partition fog invariants (global id uniqueness; no agent named 'adjudicator'). See
docs/ENGINE_CONTRACT.md (Fog / event-projection policy).
"""
from __future__ import annotations

from canon import canonical_digest

ADJUDICATOR = "adjudicator"
# Stripped from agent-visible events. event_id is adjudicator sequencing: leaving it in would leak a
# filtered opponent event via a GAP in the id sequence (ev-001, ev-003 -> "something happened at 002").
_AGENT_ONLY_EVENT_KEYS = ("event_id", "draw_ref", "source_command_id")


class FogError(ValueError):
    """A fog-of-war invariant was violated (duplicate id, agent named 'adjudicator')."""


def _entities(state_obj: dict) -> list:
    return state_obj["state"]["entities"]


def is_adjudicator_only(entity: dict) -> bool:
    """Adjudicator-only entities carry hidden information (the ROUTE_SECRET block_threshold)."""
    return entity["type"] == "ROUTE_SECRET"


def check_fog_invariants(full_state: dict, agent_ids: set) -> None:
    """Reuse the load_partition invariants for typed state: no agent named 'adjudicator';
    entity ids globally unique."""
    if ADJUDICATOR in agent_ids:
        raise FogError("no agent may be named 'adjudicator' (it would see everything)")
    seen: set = set()
    for ent in _entities(full_state):
        if ent["id"] in seen:
            raise FogError(f"duplicate entity id {ent['id']!r}")
        seen.add(ent["id"])


def project_state(viewer: str, full_state: dict) -> dict:
    """The typed state the viewer may see. Agents: public entities only (no ROUTE_SECRET, no
    full-state digest). Adjudicator: every entity. A FRESH envelope (no ``state_digest`` copied)."""
    entities = _entities(full_state)
    if viewer != ADJUDICATOR:
        entities = [e for e in entities if not is_adjudicator_only(e)]
    return {
        "schema_version": full_state["schema_version"],
        "state": {"as_of_turn": full_state["state"]["as_of_turn"], "entities": list(entities)},
    }


def _strip(ev: dict) -> dict:
    return {k: v for k, v in ev.items() if k not in _AGENT_ONLY_EVENT_KEYS}


def project_events(viewer: str, event_batch: list) -> list:
    """Per-agent event view. BLUE: own DISPATCHED + the terminal (its supply's fate). RED: own
    BLOCK_ATTEMPTED + the terminal ONLY on a route it blocked. Adjudicator: all. A failed block is
    RED's action and is NOT shown to BLUE, so RED-idle and RED-blocks-and-fails are indistinguishable."""
    if viewer == ADJUDICATOR:
        return list(event_batch)
    red_blocked = {ev["route_id"] for ev in event_batch
                   if ev["event_type"] == "ROUTE_BLOCK_ATTEMPTED"} if viewer == "RED" else set()
    out: list = []
    for ev in event_batch:
        kind = ev["event_type"]
        if kind == "SUPPLY_DISPATCHED" and viewer == "BLUE":
            out.append(_strip(ev))
        elif kind == "ROUTE_BLOCK_ATTEMPTED" and viewer == "RED":
            out.append(_strip(ev))
        elif kind in ("SUPPLY_DELIVERED", "SUPPLY_LOST"):
            if viewer == "BLUE" or (viewer == "RED" and ev["route_id"] in red_blocked):
                out.append(_strip(ev))
    return out


def project_turn_record(viewer: str, turn_record: dict, agent_ids: set | None = None) -> dict:
    """Project the adjudicator's authoritative turn record to one agent's view. The adjudicator
    receives the authority unchanged; an agent receives ONLY its public state + permitted events +
    a digest over its own projection (no full-state/adjudicator digest, seed, or raw draw)."""
    if viewer == ADJUDICATOR:
        return turn_record
    if agent_ids is not None:
        check_fog_invariants(turn_record["resulting_state"], agent_ids)
    view_state = project_state(viewer, turn_record["resulting_state"])
    view_events = project_events(viewer, turn_record["event_batch"])
    return {
        "viewer": viewer,
        "turn": turn_record["turn"],
        "state": view_state,
        "events": view_events,
        "projection_digest": canonical_digest({"state": view_state, "events": view_events}),
    }

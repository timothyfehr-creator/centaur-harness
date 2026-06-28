"""Golden-vector + property tests for core/agent_logistics.py (WP-A1a).

Same contested-logistics game as core/resolver.py (seed 0 -> d100 11 LOST, seed 3 -> d100 79 DELIVERED at
threshold 73), but each turn additionally emits a terminal TURN_ADVANCED event and advances as_of_turn —
the per-turn lineage the multi-turn replay chain check requires. The shipped contested_logistics resolver
and its committed record are NOT touched by this (separate resolver_id).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import agent_logistics as al  # noqa: E402
import resolver as rsv  # noqa: E402
import validate_turn_replay as vtr  # noqa: E402

THRESHOLD = 73


def make_state(as_of_turn: int = 0, origin: int = 100) -> dict:
    return {"schema_version": "1.0", "state": {"as_of_turn": as_of_turn, "entities": [
        {"id": "blue_supply", "type": "FORCE", "fields": {
            "origin": {"value": origin, "unit": "units"}, "in_transit": {"value": 0, "unit": "units"},
            "delivered": {"value": 0, "unit": "units"}, "loss_sink": {"value": 0, "unit": "units"}}},
        {"id": "route:r1", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": True, "unit": "bool"}}},
        {"id": "route_secret:r1", "type": "ROUTE_SECRET", "fields": {
            "subject_route": {"value": "r1", "unit": "id"},
            "block_threshold": {"value": THRESHOLD, "unit": "d100"}}}]}}


def dispatch(qty: int, route: str = "r1") -> dict:
    return {"command_id": "cmd-blue-1", "turn": 0, "actor_id": "BLUE",
            "action_type": "DISPATCH_SUPPLY", "params": {"quantity": qty, "route": route}}


def block(route: str = "r1") -> dict:
    return {"command_id": "cmd-red-1", "turn": 0, "actor_id": "RED",
            "action_type": "BLOCK_ROUTE", "params": {"route": route}}


def types(r: dict) -> list:
    return [e["event_type"] for e in r["events"]]


def as_of(r: dict) -> int:
    return r["resulting_state"]["state"]["as_of_turn"]


def test_contested_lost_seed0_advances_turn() -> None:
    r = al.transition(make_state(), [dispatch(30), block("r1")], master_seed=0)
    assert r["status"] == "resolved"
    assert types(r) == ["SUPPLY_DISPATCHED", "ROUTE_BLOCK_ATTEMPTED", "SUPPLY_LOST", "TURN_ADVANCED"]
    assert r["events"][-1]["to_turn"] == 1 and as_of(r) == 1
    assert len(r["draws"]) == 1 and r["draws"][0]["d100"] == 11


def test_contested_delivered_seed3() -> None:
    r = al.transition(make_state(), [dispatch(30), block("r1")], master_seed=3)
    assert types(r)[2] == "SUPPLY_DELIVERED" and types(r)[-1] == "TURN_ADVANCED"
    assert r["draws"][0]["d100"] == 79 and as_of(r) == 1


def test_dispatch_only_no_draw_still_advances() -> None:
    r = al.transition(make_state(), [dispatch(20)], master_seed=0)
    assert types(r) == ["SUPPLY_DISPATCHED", "SUPPLY_DELIVERED", "TURN_ADVANCED"]
    assert r["draws"] == [] and as_of(r) == 1


def test_empty_turn_advances_and_conserves() -> None:
    r = al.transition(make_state(), [], master_seed=0)
    assert types(r) == ["TURN_ADVANCED"] and as_of(r) == 1
    assert rsv.conservation_total(r["resulting_state"]) == 100


def test_two_turn_chain_as_of_turn_monotone() -> None:
    r0 = al.transition(make_state(), [dispatch(20)], master_seed=0)
    assert as_of(r0) == 1
    r1 = al.transition(r0["resulting_state"], [dispatch(20)], master_seed=0, turn=1)
    assert r1["events"][-1]["event_type"] == "TURN_ADVANCED" and r1["events"][-1]["to_turn"] == 2
    assert as_of(r1) == 2
    # conservation preserved across the chain (origin drains into delivered)
    assert rsv.conservation_total(r1["resulting_state"]) == 100


def test_legality_delegated_cross_role_rejected() -> None:
    # a RED DISPATCH_SUPPLY (role mismatch) must reject via the delegated validate_all, never go inert
    r = al.transition(make_state(), [{"command_id": "x", "turn": 0, "actor_id": "RED",
                                      "action_type": "DISPATCH_SUPPLY", "params": {"quantity": 5, "route": "r1"}}],
                      master_seed=0)
    assert r["status"] == "rejected"
    assert any(c == "role-action-mismatch" for c, _ in r["rejections"])


def test_registered_in_replay_registry_and_distinct_from_base() -> None:
    assert al.RESOLVER_ID == "agent_logistics" != rsv.RESOLVER_ID
    assert vtr._RESOLVERS.get("agent_logistics") is al
    assert al.STOCHASTIC_TERMINALS == rsv.STOCHASTIC_TERMINALS

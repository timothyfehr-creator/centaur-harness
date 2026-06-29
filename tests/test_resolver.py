"""Golden-vector + property tests for core/resolver.py (WP-E1).

Expected events and resulting state are HAND-AUTHORED from the TOTAL resolution table in
docs/ENGINE_CONTRACT.md; the seed->d100 values (seed 0 -> 11 LOST, seed 3 -> 79 DELIVERED at
threshold 73) are the independently-verified RNG-oracle values.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

import resolver as rsv  # noqa: E402

THRESHOLD = 73  # block succeeds iff d100 < 73


def make_state(threshold: int = THRESHOLD, origin: int = 100, r2_threshold: int | None = None) -> dict:
    """Default: only r1 is blockable (r2 has no route_secret -> a free route), the shipped single-secret
    topology. Pass `r2_threshold` to add a route_secret:r2 so BOTH roads are blockable -- the
    'RED matters' game (blockability is presence-derived from the route_secret, see resolver.block_thresholds)."""
    entities = [
        {"id": "blue_supply", "type": "FORCE", "fields": {
            "origin": {"value": origin, "unit": "units"},
            "in_transit": {"value": 0, "unit": "units"},
            "delivered": {"value": 0, "unit": "units"},
            "loss_sink": {"value": 0, "unit": "units"}}},
        {"id": "route:r1", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": True, "unit": "bool"}}},
        {"id": "route:r2", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"},
            "blockable": {"value": r2_threshold is not None, "unit": "bool"}}},
        {"id": "route_secret:r1", "type": "ROUTE_SECRET", "fields": {
            "subject_route": {"value": "r1", "unit": "id"},
            "block_threshold": {"value": threshold, "unit": "d100"}}},
    ]
    if r2_threshold is not None:
        entities.append({"id": "route_secret:r2", "type": "ROUTE_SECRET", "fields": {
            "subject_route": {"value": "r2", "unit": "id"},
            "block_threshold": {"value": r2_threshold, "unit": "d100"}}})
    return {"schema_version": "1.0", "state": {"as_of_turn": 0, "entities": entities}}


def dispatch(qty: int, route: str, cid: str = "cmd-blue-1") -> dict:
    return {"command_id": cid, "turn": 0, "actor_id": "BLUE",
            "action_type": "DISPATCH_SUPPLY", "params": {"quantity": qty, "route": route}}


def block(route: str, cid: str = "cmd-red-1") -> dict:
    return {"command_id": cid, "turn": 0, "actor_id": "RED",
            "action_type": "BLOCK_ROUTE", "params": {"route": route}}


def seq(result: dict) -> list[tuple]:
    return [(e["event_type"], e["route_id"], e.get("quantity")) for e in result["events"]]


def supply(result: dict) -> dict:
    return {k: v["value"] for k, v in rsv._fields(result["resulting_state"], "blue_supply").items()}


# --- golden vectors: the contested cell (the only one that draws) -------------------

def test_success_block_succeeds_supply_lost() -> None:
    # dispatch r1 30 + block r1, seed 0 -> d100 11 < 73 -> block succeeds -> LOST
    r = rsv.transition(make_state(), [dispatch(30, "r1"), block("r1")], master_seed=0)
    assert r["status"] == "resolved"
    assert seq(r) == [("SUPPLY_DISPATCHED", "r1", 30), ("ROUTE_BLOCK_ATTEMPTED", "r1", None), ("SUPPLY_LOST", "r1", 30)]
    assert supply(r) == {"origin": 70, "in_transit": 0, "delivered": 0, "loss_sink": 30}
    assert len(r["draws"]) == 1 and r["draws"][0]["d100"] == 11
    assert r["events"][-1]["draw_ref"] == "draw-001"


def test_failure_block_fails_supply_delivered() -> None:
    # dispatch r1 30 + block r1, seed 3 -> d100 79 >= 73 -> block fails -> DELIVERED
    r = rsv.transition(make_state(), [dispatch(30, "r1"), block("r1")], master_seed=3)
    assert seq(r) == [("SUPPLY_DISPATCHED", "r1", 30), ("ROUTE_BLOCK_ATTEMPTED", "r1", None), ("SUPPLY_DELIVERED", "r1", 30)]
    assert supply(r) == {"origin": 70, "in_transit": 0, "delivered": 30, "loss_sink": 0}
    assert r["draws"][0]["d100"] == 79


# --- golden vectors: the no-draw cells ----------------------------------------------

def test_dispatch_only_delivers_no_draw() -> None:
    r = rsv.transition(make_state(), [dispatch(20, "r1")], master_seed=0)
    assert seq(r) == [("SUPPLY_DISPATCHED", "r1", 20), ("SUPPLY_DELIVERED", "r1", 20)]
    assert supply(r) == {"origin": 80, "in_transit": 0, "delivered": 20, "loss_sink": 0}
    assert r["draws"] == []
    assert "draw_ref" not in r["events"][-1]


def test_block_different_route_no_draw() -> None:
    r = rsv.transition(make_state(), [dispatch(20, "r1"), block("r2")], master_seed=0)
    assert seq(r) == [("SUPPLY_DISPATCHED", "r1", 20), ("ROUTE_BLOCK_ATTEMPTED", "r2", None), ("SUPPLY_DELIVERED", "r1", 20)]
    assert r["draws"] == []


def test_r2_is_unblockable_no_draw() -> None:
    # BACKWARD-COMPAT cell: without a route_secret:r2, dispatch r2 + block r2 -> routes match BUT r2 has no
    # threshold -> no draw -> delivered. This is exactly how every pre-existing committed game stays byte-identical.
    r = rsv.transition(make_state(), [dispatch(20, "r2"), block("r2")], master_seed=0)
    assert seq(r) == [("SUPPLY_DISPATCHED", "r2", 20), ("ROUTE_BLOCK_ATTEMPTED", "r2", None), ("SUPPLY_DELIVERED", "r2", 20)]
    assert r["draws"] == []


# --- "RED matters": BOTH roads blockable when each carries a route_secret ------------
# (seed->r2-d100 at threshold 50: seed 0 -> 85 DELIVERED, seed 2 -> 45 LOST; independently RNG-oracle-verified.
# The r2 draw address embeds target_route="r2", so it draws a DIFFERENT d100 than r1 at the same seed.)

R2_THRESHOLD = 50  # the new scenario's ASSUMED, ILLUSTRATIVE r2 block threshold (block succeeds iff d100 < 50)


def test_block_thresholds_is_presence_derived() -> None:
    # the shipped single-secret state -> only r1 blockable (the dict that reproduces the old behavior)...
    assert rsv.block_thresholds(make_state()) == {"r1": THRESHOLD}
    # ...adding a route_secret:r2 makes BOTH roads blockable.
    assert rsv.block_thresholds(make_state(r2_threshold=R2_THRESHOLD)) == {"r1": THRESHOLD, "r2": R2_THRESHOLD}


def test_r2_blockable_contested_supply_lost() -> None:
    # both blockable: dispatch r2 + block r2, seed 2 -> r2 d100 45 < 50 -> block succeeds -> LOST
    r = rsv.transition(make_state(r2_threshold=R2_THRESHOLD), [dispatch(30, "r2"), block("r2")], master_seed=2)
    assert seq(r) == [("SUPPLY_DISPATCHED", "r2", 30), ("ROUTE_BLOCK_ATTEMPTED", "r2", None), ("SUPPLY_LOST", "r2", 30)]
    assert supply(r) == {"origin": 70, "in_transit": 0, "delivered": 0, "loss_sink": 30}
    assert len(r["draws"]) == 1 and r["draws"][0]["d100"] == 45
    assert r["events"][-1]["draw_ref"] == "draw-001"


def test_r2_blockable_contested_supply_delivered() -> None:
    # both blockable: dispatch r2 + block r2, seed 0 -> r2 d100 85 >= 50 -> block fails -> DELIVERED
    r = rsv.transition(make_state(r2_threshold=R2_THRESHOLD), [dispatch(30, "r2"), block("r2")], master_seed=0)
    assert seq(r) == [("SUPPLY_DISPATCHED", "r2", 30), ("ROUTE_BLOCK_ATTEMPTED", "r2", None), ("SUPPLY_DELIVERED", "r2", 30)]
    assert len(r["draws"]) == 1 and r["draws"][0]["d100"] == 85


def test_both_blockable_different_routes_no_draw() -> None:
    # both blockable, but dispatch r1 + block r2 -> routes differ -> not contested -> no draw (RED guessed wrong)
    r = rsv.transition(make_state(r2_threshold=R2_THRESHOLD), [dispatch(20, "r1"), block("r2")], master_seed=0)
    assert seq(r) == [("SUPPLY_DISPATCHED", "r1", 20), ("ROUTE_BLOCK_ATTEMPTED", "r2", None), ("SUPPLY_DELIVERED", "r1", 20)]
    assert r["draws"] == []


def test_r2_contest_uses_r2_threshold_not_r1() -> None:
    # DISCRIMINATING: seed 1 -> r2 d100 63, which falls in the [50, 72] band where r2's threshold 50 and the
    # OLD hardcoded r1 threshold 73 DISAGREE. 63 >= 50 -> DELIVERED (r2's own threshold); a regression that
    # indexed the wrong route's threshold (73) would force 63 < 73 -> LOST. Gives resolve()'s per-route
    # block_thresholds[dispatched_route] indexing genuine teeth.
    r = rsv.transition(make_state(r2_threshold=R2_THRESHOLD), [dispatch(30, "r2"), block("r2")], master_seed=1)
    assert r["draws"][0]["d100"] == 63
    assert seq(r)[-1] == ("SUPPLY_DELIVERED", "r2", 30)   # r2's threshold 50, NOT r1's 73 (which would LOSE)


def test_malformed_route_secret_is_loud_not_silently_unblockable() -> None:
    # a PRESENT but corrupt route_secret:r1 (block_threshold value missing) must NOT silently become
    # un-blockable (fail-open) -- it propagates loudly. Only an ABSENT route_secret is treated as un-blockable.
    bad = make_state()
    secret = next(e for e in bad["state"]["entities"] if e["id"] == "route_secret:r1")
    del secret["fields"]["block_threshold"]
    with pytest.raises(KeyError):
        rsv.transition(bad, [dispatch(30, "r1"), block("r1")], master_seed=0)


def test_r1_and_r2_contested_draws_are_route_distinct() -> None:
    # the contested d100 is addressed per DISPATCHED route, so at the same seed the two roads are
    # INDEPENDENT gambles (r1-on-r1 vs r2-on-r2 draw different d100). Adding route_secret:r2 does not
    # perturb r1's draw (the address embeds the route, not the state), so seed 0 r1 stays 11.
    st = make_state(r2_threshold=R2_THRESHOLD)
    d_r1 = rsv.transition(st, [dispatch(30, "r1"), block("r1")], master_seed=0)["draws"][0]["d100"]
    d_r2 = rsv.transition(st, [dispatch(30, "r2"), block("r2")], master_seed=0)["draws"][0]["d100"]
    assert d_r1 == 11 and d_r2 == 85 and d_r1 != d_r2


def test_empty_turn_is_legal_and_noop() -> None:
    r = rsv.transition(make_state(), [], master_seed=0)
    assert r["status"] == "resolved"
    assert r["events"] == [] and r["draws"] == []
    assert supply(r) == {"origin": 100, "in_transit": 0, "delivered": 0, "loss_sink": 0}


def test_command_legality_per_command_check() -> None:
    # WP-A2a: command_legality returns the FIRST legality reject code (or None) for ONE harness-bound command,
    # reusing validate_all so the agent layer can forfeit/re-verify an illegal move without forking the rules.
    s = make_state()
    legal_blue = {"actor_id": "BLUE", "action_type": "DISPATCH_SUPPLY", "params": {"quantity": 30, "route": "r1"}}
    legal_red = {"actor_id": "RED", "action_type": "BLOCK_ROUTE", "params": {"route": "r1"}}
    assert rsv.command_legality(legal_blue, s) is None
    assert rsv.command_legality(legal_red, s) is None
    # each illegal shape -> its code (the codes the live models actually tripped + the route/actor cases)
    assert rsv.command_legality({**legal_blue, "params": {"quantity": 50, "route": "r1"}}, s) == "out-of-range"
    assert rsv.command_legality({"actor_id": "RED", "action_type": "DISPATCH_SUPPLY",
                                 "params": {"quantity": 30, "route": "r1"}}, s) == "role-action-mismatch"
    assert rsv.command_legality({**legal_blue, "params": {"quantity": 30, "route": "r9"}}, s) == "unknown-route"
    assert rsv.command_legality({**legal_blue, "actor_id": "GREEN"}, s) == "unknown-actor"
    # WP-A3 M1: legality is now STATE-DEPENDENT — over-dispatching more than remaining origin is rejected
    low = make_state(origin=5)
    assert rsv.command_legality(legal_blue, low) == "insufficient-supply"          # dispatch 30 > origin 5
    assert rsv.command_legality({**legal_blue, "params": {"quantity": 5, "route": "r1"}}, low) is None  # 5 <= 5 OK
    assert set(rsv.LEGALITY_REJECT_CODES) >= {"out-of-range", "role-action-mismatch", "unknown-route",
                                              "unknown-actor", "invalid-enum", "too-many-commands",
                                              "insufficient-supply"}


# --- invariants & rejections --------------------------------------------------------

def red_dispatch(qty: int = 10, route: str = "r1") -> dict:
    """A RED actor issuing BLUE's action (would validate-then-go-inert before the legality fix)."""
    return {"command_id": "cmd-x", "turn": 0, "actor_id": "RED",
            "action_type": "DISPATCH_SUPPLY", "params": {"quantity": qty, "route": route}}


def blue_block(route: str = "r1") -> dict:
    """A BLUE actor issuing RED's action (would validate-then-go-inert before the legality fix)."""
    return {"command_id": "cmd-y", "turn": 0, "actor_id": "BLUE",
            "action_type": "BLOCK_ROUTE", "params": {"route": route}}


def green_dispatch(qty: int = 10, route: str = "r1") -> dict:
    """An unknown actor (would be silently ignored by resolve() before the legality fix)."""
    return {"command_id": "cmd-z", "turn": 0, "actor_id": "GREEN",
            "action_type": "DISPATCH_SUPPLY", "params": {"quantity": qty, "route": route}}


@pytest.mark.parametrize("cmds,code", [
    ([dispatch(31, "r1")], "out-of-range"),
    ([dispatch(0, "r1")], "out-of-range"),
    ([dispatch(10, "r3")], "unknown-route"),
    ([block("r3")], "unknown-route"),
    ([dispatch(10, "r1"), dispatch(5, "r2")], "too-many-commands"),
    # legality fix: actor enum + role/action capability (closes the legal-but-inert trapdoor)
    ([green_dispatch()], "unknown-actor"),
    ([red_dispatch()], "role-action-mismatch"),
    ([blue_block()], "role-action-mismatch"),
    ([{"command_id": "c1", "turn": 0, "actor_id": "BLUE",
       "action_type": "NUKE", "params": {}}], "invalid-enum"),
])
def test_invalid_commands_rejected_zero_mutation(cmds: list, code: str) -> None:
    state = make_state()
    r = rsv.transition(state, cmds, master_seed=0)
    assert r["status"] == "rejected"
    assert any(c == code for c, _ in r["rejections"])
    assert r["events"] == [] and r["resulting_state"] is state  # unchanged


def test_cross_role_and_unknown_actor_are_rejected_not_inert() -> None:
    """The legal-but-inert trapdoor: a cross-role or unknown-actor command must be REJECTED
    (commit no record, zero mutation), never accepted-then-ignored by resolve()."""
    for cmds in ([red_dispatch()], [blue_block()], [green_dispatch()]):
        r = rsv.transition(make_state(), cmds, master_seed=0)
        assert r["status"] == "rejected", f"{cmds} should be rejected, not inert"
        assert r["events"] == [] and r["draws"] == []
        assert supply(r) == {"origin": 100, "in_transit": 0, "delivered": 0, "loss_sink": 0}


def test_conservation_holds_for_every_resolved_case() -> None:
    for cmds, seed in [([dispatch(30, "r1"), block("r1")], 0), ([dispatch(30, "r1"), block("r1")], 3),
                       ([dispatch(20, "r1")], 0), ([dispatch(20, "r2"), block("r2")], 0), ([], 0)]:
        r = rsv.transition(make_state(), cmds, master_seed=seed)
        assert rsv.conservation_total(r["resulting_state"]) == 100
        assert rsv.is_non_negative(r["resulting_state"])


# --- reduce() grammar (rejects malformed batches even if conservation holds) ---------

def test_reduce_rejects_route_mismatch() -> None:
    bad = [{"event_type": "SUPPLY_DISPATCHED", "route_id": "r1", "quantity": 30},
           {"event_type": "SUPPLY_DELIVERED", "route_id": "r2", "quantity": 30}]
    with pytest.raises(rsv.ResolveError):
        rsv.reduce(make_state(), bad)


def test_reduce_rejects_terminal_before_dispatch() -> None:
    with pytest.raises(rsv.ResolveError):
        rsv.reduce(make_state(), [{"event_type": "SUPPLY_DELIVERED", "route_id": "r1", "quantity": 30}])


# --- determinism & command-order invariance (PASS#1 / #5 preview) -------------------

def test_determinism() -> None:
    a = rsv.transition(make_state(), [dispatch(30, "r1"), block("r1")], master_seed=0)
    b = rsv.transition(make_state(), [dispatch(30, "r1"), block("r1")], master_seed=0)
    assert a["events"] == b["events"] and supply(a) == supply(b)


def test_command_order_does_not_change_events() -> None:
    forward = rsv.transition(make_state(), [dispatch(30, "r1"), block("r1")], master_seed=0)
    reverse = rsv.transition(make_state(), [block("r1"), dispatch(30, "r1")], master_seed=0)
    assert forward["events"] == reverse["events"]

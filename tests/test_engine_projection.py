"""Typed-state projector / fog tests (WP-E1) -> PASS condition #4 (no-leak) + the projection policy.

Mirrors the leak-test pattern of test_context_compiler.py, extended to digests/seeds/draws and the
event-projection policy (BLUE never sees RED's failed block; RED-idle and RED-blocks-and-fails are
byte-indistinguishable to BLUE).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))

import canon  # noqa: E402
import engine_projection as ep  # noqa: E402
import turn_record as tr  # noqa: E402

FP = {"engine_source_hash": "fixed", "python": "x", "pyyaml_version": "x",
      "serializer_version": "1", "persistence_profile": "local-posix-fs-v1"}


def make_state(threshold: int = 73) -> dict:
    return {"schema_version": "1.0", "state": {"as_of_turn": 0, "entities": [
        {"id": "blue_supply", "type": "FORCE", "fields": {
            "origin": {"value": 100, "unit": "units"}, "in_transit": {"value": 0, "unit": "units"},
            "delivered": {"value": 0, "unit": "units"}, "loss_sink": {"value": 0, "unit": "units"}}},
        {"id": "route:r1", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": True, "unit": "bool"}}},
        {"id": "route:r2", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": False, "unit": "bool"}}},
        {"id": "route_secret:r1", "type": "ROUTE_SECRET", "fields": {
            "subject_route": {"value": "r1", "unit": "id"},
            "block_threshold": {"value": threshold, "unit": "d100"}}}]}}

def disp(q, r): return {"command_id": "cb", "turn": 0, "actor_id": "BLUE",
                        "action_type": "DISPATCH_SUPPLY", "params": {"quantity": q, "route": r}}
def blk(r): return {"command_id": "cr", "turn": 0, "actor_id": "RED",
                    "action_type": "BLOCK_ROUTE", "params": {"route": r}}

def record(commands, seed, threshold=73):
    return tr.assemble(turn=0, start_state=make_state(threshold), commands=commands, master_seed=seed,
                       runtime_fingerprint=FP, successor_slot="run/turns/0000.json")["turn_record"]

def blue_bytes(rec):
    return canon.canonical_bytes(ep.project_turn_record("BLUE", rec))

def entity_ids(view):
    return {e["id"] for e in view["state"]["state"]["entities"]}


# --- PASS#4: the adjudicator's hidden state never reaches an agent -------------------

def test_blue_sees_public_entities_not_route_secret() -> None:
    rec = record([disp(30, "r1"), blk("r1")], 0)            # LOST (d100 11 < 73)
    view = ep.project_turn_record("BLUE", rec)
    assert entity_ids(view) == {"blue_supply", "route:r1", "route:r2"}
    assert "route_secret:r1" not in entity_ids(view)


@pytest.mark.parametrize("forbidden", [
    "route_secret", "block_threshold", "ROUTE_BLOCK_ATTEMPTED", "master_seed", "draw_ref",
])
def test_blue_view_leaks_no_adjudicator_token(forbidden: str) -> None:
    rec = record([disp(30, "r1"), blk("r1")], 0)            # contested -> draw consumed, RED blocks
    text = blue_bytes(rec).decode("utf-8")
    assert forbidden not in text


def test_blue_view_leaks_no_seed_draw_or_fullstate_digest() -> None:
    rec = record([disp(30, "r1"), blk("r1")], 0)
    text = blue_bytes(rec).decode("utf-8")
    assert str(rec["draw_records"][0]["raw_uint"]) not in text          # the raw draw value
    assert rec["resulting_state"]["state_digest"]["value"] not in text  # the full-state digest
    # (the hidden threshold's absence is covered structurally by route_secret being filtered out;
    #  a bare "73" substring check is unreliable -- it matches by chance inside a sha256 hex digest)


def test_blue_view_is_not_empty() -> None:
    # sanity: BLUE still sees its own dispatch + the terminal (over-stripping would be a bug)
    view = ep.project_turn_record("BLUE", record([disp(30, "r1"), blk("r1")], 0))
    kinds = [e["event_type"] for e in view["events"]]
    assert kinds == ["SUPPLY_DISPATCHED", "SUPPLY_LOST"]


# --- the policy: a FAILED block is invisible to BLUE --------------------------------

def test_red_idle_and_red_failed_block_are_identical_to_blue() -> None:
    idle = record([disp(30, "r1")], 0)                     # no block -> DELIVERED
    failed = record([disp(30, "r1"), blk("r1")], 3)        # d100 79 >= 73 -> block FAILS -> DELIVERED
    assert blue_bytes(idle) == blue_bytes(failed)


def test_threshold_variation_at_fixed_outcome_is_invisible_to_blue() -> None:
    # seed 3 -> d100 79; thresholds 73 and 50 both fail the block (79 >= both) -> DELIVERED
    assert blue_bytes(record([disp(30, "r1"), blk("r1")], 3, threshold=73)) \
        == blue_bytes(record([disp(30, "r1"), blk("r1")], 3, threshold=50))


# --- adjudicator authority + fog invariants -----------------------------------------

def test_adjudicator_sees_the_authority_unchanged() -> None:
    rec = record([disp(30, "r1"), blk("r1")], 0)
    assert ep.project_turn_record("adjudicator", rec) is rec

def test_fog_invariants_reject_adjudicator_agent_and_dupe_ids() -> None:
    rec = record([disp(30, "r1")], 0)
    with pytest.raises(ep.FogError):
        ep.project_turn_record("BLUE", rec, agent_ids={"BLUE", "adjudicator"})
    dupe = make_state()
    dupe["state"]["entities"].append(dupe["state"]["entities"][0])  # duplicate blue_supply id
    with pytest.raises(ep.FogError):
        ep.check_fog_invariants(dupe, {"BLUE", "RED"})


# --- ECI-1: the record-level `ruleset` (salvo per-pairing p_intercept) never reaches an agent -------

AGENT_VIEW_KEYS = {"viewer", "turn", "state", "events", "projection_digest"}


def test_agent_view_keys_are_a_fixed_allowlist() -> None:
    # The projector is allowlist-CONSTRUCTED: an agent view is EXACTLY these keys. Pinning the set means
    # a future top-level turn-record field (e.g. the salvo `ruleset`) cannot silently pass through.
    view = ep.project_turn_record("BLUE", record([disp(30, "r1"), blk("r1")], 0))
    assert set(view) == AGENT_VIEW_KEYS


def test_record_level_ruleset_is_never_projected_to_an_agent() -> None:
    # WP-E2a added a top-level `ruleset` to the turn record; per-pairing p_intercept is outcome-
    # determining HIDDEN info (ECI-1). Two records identical except for `ruleset` must project to
    # byte-identical BLUE views, and `ruleset` must appear NOWHERE in the projection.
    base = record([disp(30, "r1"), blk("r1")], 0)
    a = {**base, "ruleset": {"p_intercept_pct": 80}}
    b = {**base, "ruleset": {"p_intercept_pct": 60}}
    assert "ruleset" not in ep.project_turn_record("BLUE", a)
    assert "p_intercept_pct" not in blue_bytes(a).decode("utf-8")
    assert blue_bytes(a) == blue_bytes(b) == blue_bytes(base)

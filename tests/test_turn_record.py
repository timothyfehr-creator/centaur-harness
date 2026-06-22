"""Turn-record + commit-machinery tests (WP-E1) -> PASS conditions #1, #7, #9, #10, #12 + idempotency.

These exercise the SINGLE DURABLE AUTHORITY: the committed turn record, from which the resulting
state is independently re-derivable. A fixed runtime_fingerprint is injected so byte-identity is
deterministic (the live git fingerprint is the engine entrypoint's concern, not the contract's).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))

import atomic  # noqa: E402
import canon  # noqa: E402
import resolver as rsv  # noqa: E402
import turn_record as tr  # noqa: E402

FP = {"engine_source_hash": "fixed-for-tests", "python": "x", "pyyaml_version": "x",
      "serializer_version": "1", "persistence_profile": "local-posix-fs-v1"}
THRESHOLD = 73


def make_state(threshold: int = THRESHOLD) -> dict:
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

def disp(q: int, r: str) -> dict:
    return {"command_id": "cb", "turn": 0, "actor_id": "BLUE", "action_type": "DISPATCH_SUPPLY",
            "params": {"quantity": q, "route": r}}

def blk(r: str) -> dict:
    return {"command_id": "cr", "turn": 0, "actor_id": "RED", "action_type": "BLOCK_ROUTE",
            "params": {"route": r}}

def rec_for(commands: list, seed: int, slot: str = "run/turns/0000.json", threshold: int = THRESHOLD) -> dict:
    return tr.assemble(turn=0, start_state=make_state(threshold), commands=commands,
                       master_seed=seed, runtime_fingerprint=FP, successor_slot=slot)["turn_record"]


# --- PASS#1: command file/order reordering does not change the record ----------------

def test_command_reorder_yields_identical_record_bytes() -> None:
    a = rec_for([disp(30, "r1"), blk("r1")], seed=0)
    b = rec_for([blk("r1"), disp(30, "r1")], seed=0)
    assert canon.canonical_bytes(a) == canon.canonical_bytes(b)
    assert a["transition_input_hash"] == b["transition_input_hash"]


# --- PASS#7: seed changes the hash ONLY when a draw is involved ----------------------

def test_seed_changes_hash_when_draw_consumed() -> None:
    assert rec_for([disp(30, "r1"), blk("r1")], 0)["transition_input_hash"] \
        != rec_for([disp(30, "r1"), blk("r1")], 3)["transition_input_hash"]

def test_no_draw_turn_is_seed_independent() -> None:
    a = rec_for([disp(20, "r1")], 0)
    b = rec_for([disp(20, "r1")], 999)
    assert a["rng"] is None
    assert a["transition_input_hash"] == b["transition_input_hash"]
    assert canon.canonical_bytes(a) == canon.canonical_bytes(b)


# --- PASS#9: reduce(committed start, committed events) == committed resulting bytes --
# independent verifier path: read the committed bytes back, re-derive, compare.

def test_reduce_coherence_via_independent_reverify(tmp_path: Path) -> None:
    rec = rec_for([disp(30, "r1"), blk("r1")], 0)
    slot = str(tmp_path / "turns" / "0000.json")
    tr.commit(rec, slot)
    committed = json.loads(Path(slot).read_bytes())
    rederived = rsv.reduce(committed["start_state"], committed["event_batch"])
    # the resulting STATE field re-derives byte-for-byte; the committed state_digest matches it
    assert canon.canonical_bytes(rederived["state"]) == canon.canonical_bytes(committed["resulting_state"]["state"])
    assert canon.canonical_digest(rederived["state"]) == committed["resulting_state"]["state_digest"]


def test_state_envelopes_carry_state_digest_over_state_field_only() -> None:
    # round-3 C7: state is an envelope {schema_version, state, state_digest}; the digest is over the
    # `state` field ONLY (self-reference excluded), domain canonical.
    rec = rec_for([disp(30, "r1"), blk("r1")], 0)
    for key in ("start_state", "resulting_state"):
        env = rec[key]
        assert set(env) >= {"schema_version", "state", "state_digest"}
        assert env["state_digest"] == canon.canonical_digest(env["state"])
        assert env["state_digest"]["domain"] == "canonical"
    # the digests block uses the state_digest (state field only), not a digest of the whole envelope
    assert rec["digests"]["start_state"] == rec["start_state"]["state_digest"]
    assert rec["digests"]["resulting_state"] == rec["resulting_state"]["state_digest"]


# --- PASS#10: single successor per head; idempotent retry ----------------------------

def test_single_successor_and_idempotent_retry(tmp_path: Path) -> None:
    slot = str(tmp_path / "turns" / "0000.json")
    a = rec_for([disp(30, "r1"), blk("r1")], 0)
    b = rec_for([disp(30, "r1"), blk("r1")], 3)  # different candidate (seed -> different tih)
    assert tr.commit(a, slot) == "committed"
    assert tr.commit(a, slot) == "idempotent"           # byte-identical retry
    with pytest.raises(atomic.SlotConflict):
        tr.commit(b, slot)                              # a different turn cannot take the slot


# --- PASS#12: draw -> event coherence (recompute the draw, re-resolve) ---------------

def test_draw_event_coherence(tmp_path: Path) -> None:
    import rng
    for seed, expect in [(0, "SUPPLY_LOST"), (3, "SUPPLY_DELIVERED")]:
        rec = rec_for([disp(30, "r1"), blk("r1")], seed)
        slot = str(tmp_path / f"turns_{seed}" / "0000.json")
        tr.commit(rec, slot)
        committed = json.loads(Path(slot).read_bytes())
        # recompute the draw from the committed seed + address; confirm it matches and the
        # terminal event is its correct consequence (block succeeds iff d100 < threshold)
        addr = committed["draw_records"][0]["address"]
        d100 = rng.draw(committed["rng"]["master_seed"], addr)["d100"]
        assert d100 == committed["draw_records"][0]["d100"]
        threshold = THRESHOLD
        terminal = committed["event_batch"][-1]
        assert terminal["event_type"] == expect
        assert (terminal["event_type"] == "SUPPLY_LOST") == (d100 < threshold)
        # every stochastic terminal references exactly one consumed draw, and vice versa
        assert terminal.get("draw_ref") == committed["draw_records"][0]["draw_id"]
        assert len(committed["draw_records"]) == 1


# --- rejected turn commits NO record; atomic_write basics ---------------------------

def test_rejected_turn_yields_no_record() -> None:
    out = tr.assemble(turn=0, start_state=make_state(), commands=[disp(31, "r1")],
                      master_seed=0, runtime_fingerprint=FP, successor_slot="s")
    assert out["status"] == "rejected" and out["turn_record"] is None

def test_atomic_write_replaces_and_cleans_tmp(tmp_path: Path) -> None:
    target = tmp_path / "a" / "x.json"
    atomic.atomic_write(target, b'{"hello":1}')
    assert target.read_bytes() == b'{"hello":1}'
    atomic.atomic_write(target, b'{"hello":2}')             # durable replace
    assert target.read_bytes() == b'{"hello":2}'
    assert not (tmp_path / "a" / ".x.json.tmp").exists()    # tmp cleaned up by os.replace

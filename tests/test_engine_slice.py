"""WP-E1 acceptance suite — the 12 PASS conditions of docs/ENGINE_CONTRACT.md, end to end.

Some conditions are also covered by the per-module tests; this file is the consolidated Definition
of Done, one named test per condition.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import atomic  # noqa: E402
import canon  # noqa: E402
import engine_projection as ep  # noqa: E402
import engine_recompute as er  # noqa: E402
import resolver as rsv  # noqa: E402
import turn_record as tr  # noqa: E402

THRESHOLD = 73


def rec(commands, seed):
    return er.assemble_slice(seed, commands=commands)["turn_record"]

def disp(q, r, cid="cb"): return {"command_id": cid, "turn": 0, "actor_id": "BLUE",
                                  "action_type": "DISPATCH_SUPPLY", "params": {"quantity": q, "route": r}}
def blk(r, cid="cr"): return {"command_id": cid, "turn": 0, "actor_id": "RED",
                              "action_type": "BLOCK_ROUTE", "params": {"route": r}}
CONTESTED = [disp(30, "r1"), blk("r1")]


def test_pass01_command_reorder_yields_identical_record() -> None:
    assert canon.canonical_bytes(rec([disp(30, "r1"), blk("r1")], 0)) \
        == canon.canonical_bytes(rec([blk("r1"), disp(30, "r1")], 0))


def test_pass02_fresh_subprocess_recompute_is_hashseed_independent() -> None:
    script = str(REPO_ROOT / "scripts" / "engine_recompute.py")
    outs = []
    for hashseed in ("0", "1", "17"):                          # PYTHONHASHSEED, set EXTERNALLY
        env = {**os.environ, "PYTHONHASHSEED": hashseed}
        r = subprocess.run([sys.executable, script, "--seed", "0"], cwd=REPO_ROOT,
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout.strip())
    assert len(set(outs)) == 1, f"recompute hash varied across PYTHONHASHSEED / processes: {outs}"


def test_pass03_invalid_command_commits_no_record(tmp_path: Path) -> None:
    out = er.assemble_slice(0, commands=[disp(31, "r1")])       # over-capacity
    assert out["status"] == "rejected" and out["turn_record"] is None
    # nothing to commit -> the successor slot is never created
    slot = tmp_path / "turns" / "0000.json"
    assert not slot.exists()


def test_pass04_blue_view_leaks_no_adjudicator_secret() -> None:
    view = ep.project_turn_record("BLUE", rec(CONTESTED, 0))
    text = canon.canonical_bytes(view).decode("utf-8")
    for forbidden in ("route_secret", "block_threshold", "master_seed", "draw_ref", "ROUTE_BLOCK_ATTEMPTED"):
        assert forbidden not in text


def test_pass05_caches_re_derive_from_the_committed_record(tmp_path: Path) -> None:
    r = rec(CONTESTED, 0)
    slot = str(tmp_path / "turns" / "0000.json")
    tr.commit(r, slot)
    committed = json.loads(Path(slot).read_bytes())             # "delete caches", read the authority
    rederived = rsv.reduce(committed["start_state"], committed["event_batch"])
    assert canon.canonical_bytes(rederived["state"]) == canon.canonical_bytes(committed["resulting_state"]["state"])


def test_pass06_every_draw_carries_address_raw_and_rule() -> None:
    d = rec(CONTESTED, 0)["draw_records"][0]
    assert set(d) >= {"draw_id", "address", "raw_uint", "d100", "consuming_rule_id"}


def test_pass07_seed_changes_hash_only_when_a_draw_is_involved() -> None:
    assert rec(CONTESTED, 0)["transition_input_hash"] != rec(CONTESTED, 3)["transition_input_hash"]
    a, b = rec([disp(20, "r1")], 0), rec([disp(20, "r1")], 999)   # no draw
    assert a["rng"] is None and a["transition_input_hash"] == b["transition_input_hash"]


def test_pass08_ordered_events_and_no_decorative_seed() -> None:
    assert [e["event_type"] for e in rec(CONTESTED, 0)["event_batch"]] \
        == ["SUPPLY_DISPATCHED", "ROUTE_BLOCK_ATTEMPTED", "SUPPLY_LOST"]
    assert rec([disp(20, "r1")], 0)["rng"] is None              # no draw -> no rng block


def test_pass09_reduce_coherence_on_committed_bytes(tmp_path: Path) -> None:
    r = rec(CONTESTED, 0)
    slot = str(tmp_path / "turns" / "0000.json")
    tr.commit(r, slot)
    committed = json.loads(Path(slot).read_bytes())
    assert canon.canonical_digest(rsv.reduce(committed["start_state"], committed["event_batch"])["state"]) \
        == committed["resulting_state"]["state_digest"]


def test_pass10_single_successor_per_head(tmp_path: Path) -> None:
    slot = str(tmp_path / "turns" / "0000.json")
    assert tr.commit(rec(CONTESTED, 0), slot) == "committed"
    assert tr.commit(rec(CONTESTED, 0), slot) == "idempotent"
    with pytest.raises(atomic.SlotConflict):
        tr.commit(rec(CONTESTED, 3), slot)                     # different candidate (seed)


def test_pass11_command_id_change_does_not_reroll() -> None:
    a = rec([disp(30, "r1", cid="x"), blk("r1", cid="y")], 0)
    b = rec([disp(30, "r1", cid="P"), blk("r1", cid="Q")], 0)  # only command_ids differ
    assert a["draw_records"][0]["d100"] == b["draw_records"][0]["d100"]          # same draw
    assert a["event_batch"][-1]["event_type"] == b["event_batch"][-1]["event_type"]


def test_pass12_draw_to_event_coherence() -> None:
    import rng
    for seed, expect in [(0, "SUPPLY_LOST"), (3, "SUPPLY_DELIVERED")]:
        r = rec(CONTESTED, seed)
        addr = r["draw_records"][0]["address"]
        d100 = rng.draw(r["rng"]["master_seed"], addr)["d100"]   # recompute the draw
        assert d100 == r["draw_records"][0]["d100"]
        assert r["event_batch"][-1]["event_type"] == expect
        assert (expect == "SUPPLY_LOST") == (d100 < THRESHOLD)

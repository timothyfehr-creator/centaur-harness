"""WP-E2b2 multi-turn campaign tests — the orchestrator + the cross-record continuity invariant.

The committed campaign (examples/ru_ua_salvo_multiturn/run/turns/*.json) chains weekly turns until
culmination. These assert the chain is sound (continuity is tested DIRECTLY here, before the gate of
commit 2 formalizes it), each record replays per-record, and the campaign BDA shape + streak semantics +
the leading-indicator-leads-culmination property hold.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import atomic  # noqa: E402
import canon  # noqa: E402
import turn_record as tr  # noqa: E402
import campaign_run as cr  # noqa: E402
import validate_turn_replay as vtr  # noqa: E402

TURNS = sorted((REPO_ROOT / "examples" / "ru_ua_salvo_multiturn" / "run" / "turns").glob("*.json"))
RECORDS = [json.loads(p.read_bytes()) for p in TURNS]


def _culm(rec: dict) -> bool:
    return any(e["event_type"] == "CULMINATION_STATUS" and e["culminated"] for e in rec["event_batch"])


def _leth(rec: dict) -> dict:
    return next(e for e in rec["event_batch"] if e["event_type"] == "LETHALITY_STATUS")


# --- the committed golden campaign ----------------------------------------------------------------

def test_campaign_is_a_multi_record_chain_that_culminates() -> None:
    assert len(RECORDS) >= 2
    assert _culm(RECORDS[-1])                                  # stops ON culmination
    assert not any(_culm(r) for r in RECORDS[:-1])             # and not before


def test_cross_record_continuity_byte_identical_handoff() -> None:
    for i in range(1, len(RECORDS)):
        assert RECORDS[i]["start_state"] == RECORDS[i - 1]["resulting_state"]    # byte-identical handoff
        assert RECORDS[i]["turn"] == RECORDS[i - 1]["turn"] + 1                  # monotone turns
        assert RECORDS[i - 1]["successor_slot"] == f"run/turns/{i:04d}.json"     # forward pointer


def test_every_committed_record_passes_per_record_replay() -> None:
    for i, rec in enumerate(RECORDS):
        assert vtr.check_record(rec, f"wk{i}") == []


def test_campaign_conservation_and_leading_indicator_leads_culmination() -> None:
    first_zero_weeks = None
    first_culm = None
    for rec in RECORDS:
        ev = {e["event_type"]: e for e in rec["event_batch"]}
        launched = sum(e["count"] for e in rec["event_batch"] if e["event_type"] == "STRIKES_LAUNCHED")
        intercepted = sum(e["count"] for e in rec["event_batch"] if e["event_type"] == "STRIKES_INTERCEPTED")
        leaked = sum(e["count"] for e in rec["event_batch"] if e["event_type"] == "STRIKES_LEAKED")
        assert launched == intercepted + leaked               # conservation every week
        if first_zero_weeks is None and ev["MAGAZINE_STATUS"]["weeks_remaining"] == 0:
            first_zero_weeks = rec["turn"]
        if first_culm is None and ev["CULMINATION_STATUS"]["culminated"]:
            first_culm = rec["turn"]
    # the magazine weeks-of-supply indicator drops to 0 strictly BEFORE the culmination flips (leads it)
    assert first_zero_weeks is not None and first_culm is not None and first_zero_weeks < first_culm


def test_streak_builds_then_fires_collapse_at_k() -> None:
    streaks = [_leth(r)["streak"] for r in RECORDS]
    assert streaks[-1] >= 3 and _leth(RECORDS[-1])["lethality_collapsed"] is True   # sustained-k fired


# --- the orchestrator (pure run + commit, into tmp) -----------------------------------------------

def test_run_campaign_is_deterministic() -> None:
    state, ruleset = cr.load_scenario()
    a, reason_a = cr.run_campaign(state, ruleset)
    b, reason_b = cr.run_campaign(state, ruleset)
    assert reason_a == reason_b == "culminated"
    assert [canon.canonical_bytes(x) for x in a] == [canon.canonical_bytes(x) for x in b]


def test_run_campaign_stops_at_horizon_when_never_culminating() -> None:
    state, ruleset = cr.load_scenario()
    rich = copy.deepcopy(state)
    for e in rich["state"]["entities"]:                       # magazines that never deplete -> no collapse
        if e["id"].startswith("ukraine_intc_"):
            e["fields"]["interceptor_inventory"]["value"] = 10_000_000
            e["fields"]["weekly_resupply"]["value"] = 10_000_000
    recs, reason = cr.run_campaign(rich, ruleset, max_weeks=5)
    assert reason == "reached-horizon" and len(recs) == 5
    assert not any(_culm(r) for r in recs)


def test_commit_campaign_idempotent_then_conflict(tmp_path: Path) -> None:
    state, ruleset = cr.load_scenario()
    recs, _ = cr.run_campaign(state, ruleset, max_weeks=2)
    slot = tmp_path / "turns" / "0000.json"
    slot.parent.mkdir(parents=True)
    assert tr.commit(recs[0], str(slot)) == "committed"
    assert tr.commit(recs[0], str(slot)) == "idempotent"      # re-running the same campaign is safe
    bad = copy.deepcopy(recs[0])
    bad["transition_input_hash"] = "0" * 64
    with pytest.raises(atomic.SlotConflict):
        tr.commit(bad, str(slot))                             # a changed record on an existing slot fails

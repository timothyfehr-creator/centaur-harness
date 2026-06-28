"""Behavior tests for scripts/agent_offline_campaign.py (the multi-turn offline campaign, WP-A1a).

A campaign chains drive_turn: turn N's SEALED resulting_state becomes turn N+1's start_state byte-
identically. The committed chain must pass validate_turn_replay's chain check and bind per turn.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = REPO_ROOT / "examples" / "contested_logistics_campaign"
REPLAY = REPO_ROOT / "scripts" / "validate_turn_replay.py"
PROV = REPO_ROOT / "scripts" / "validate_agent_provenance.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import agent_offline_campaign as camp  # noqa: E402
import agent_offline_run as drive  # noqa: E402
from canon import canonical_digest  # noqa: E402


def _bytes() -> dict:
    return {"BLUE": (REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid" / "dispatch_r1.json").read_bytes()}


def test_run_campaign_chains_byte_identically() -> None:
    drivens = camp.run_campaign(drive.INITIAL_STATE, [_bytes() for _ in range(3)], run_id="c")
    assert len(drivens) == 3
    for i, d in enumerate(drivens):
        rec = d["turn_record"]
        assert rec["turn"] == i
        assert rec["start_state"]["state"]["as_of_turn"] == i
        assert rec["resulting_state"]["state"]["as_of_turn"] == i + 1
        if i > 0:
            prev = drivens[i - 1]["turn_record"]
            # the head handoff is byte-identical (turn i start == turn i-1 resulting)
            assert rec["start_state"]["state_digest"] == prev["resulting_state"]["state_digest"]
            assert canonical_digest(rec["start_state"]["state"]) == prev["resulting_state"]["state_digest"]


def test_run_campaign_conserves_supply() -> None:
    drivens = camp.run_campaign(drive.INITIAL_STATE, [_bytes() for _ in range(3)], run_id="c")
    final = {e["id"]: e for e in drivens[-1]["turn_record"]["resulting_state"]["state"]["entities"]}["blue_supply"]
    f = final["fields"]
    assert sum(f[k]["value"] for k in ("origin", "in_transit", "delivered", "loss_sink")) == 100
    assert f["delivered"]["value"] == 90 and f["origin"]["value"] == 10   # 3 x 30 dispatched + delivered


def test_committed_campaign_chain_replays() -> None:
    # the chain check: ordered, gap-free, byte-identical handoff, monotone as_of_turn, one resolver
    paths = sorted((CAMPAIGN / "run" / "turns").glob("*.json"))
    assert len(paths) == 3
    r = subprocess.run([sys.executable, str(REPLAY), *(str(p) for p in paths)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_committed_campaign_binds_per_turn() -> None:
    r = subprocess.run([sys.executable, str(PROV), "--scenario-dir", str(CAMPAIGN)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "3 step(s) bound" in r.stdout

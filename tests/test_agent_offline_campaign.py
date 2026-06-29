"""Behavior tests for scripts/agent_offline_campaign.py (the multi-turn offline campaign, WP-A1a).

A campaign chains drive_turn: turn N's SEALED resulting_state becomes turn N+1's start_state byte-
identically. The committed chain must pass validate_turn_replay's chain check and bind per turn.
"""
from __future__ import annotations

import json
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


# --- WP-A3 M3: multi-turn coverage of the distinct game paths (free, deterministic) -----------------

def _tool_use(action_type: str, params: dict) -> bytes:
    return json.dumps({"role": "assistant", "content": [{"type": "tool_use", "name": "submit_command",
        "input": {"action_type": action_type, "params": params}}]}).encode()


def _origin(driven: dict) -> int:
    return driven["turn_record"]["resulting_state"]["state"]["entities"][0]["fields"]["origin"]["value"]


def test_campaign_supply_exhaustion_forfeits_not_crash() -> None:
    # WP-A3 M1 in a real multi-turn game: dispatch 30 each turn from origin 100 -> turns 0-2 deliver (100->10),
    # turn 3's 30-dispatch exceeds remaining 10 -> ILLEGAL_FORFEIT insufficient-supply, the chain CONTINUES
    # (no invariant-violation crash). This is the bug a multi-turn deliver-streak would otherwise hit.
    drivens = camp.run_campaign(drive.INITIAL_STATE, [_bytes() for _ in range(4)], run_id="c")
    kinds = [d["llm_steps"][0]["step_kind"] for d in drivens]
    assert kinds == ["COMMAND", "COMMAND", "COMMAND", "ILLEGAL_FORFEIT"]
    assert drivens[3]["llm_steps"][0]["reject_code"] == "insufficient-supply"
    assert drivens[3]["turn_record"]["command_batch"] == []          # forfeited -> empty turn
    assert [_origin(d) for d in drivens] == [70, 40, 10, 10]         # depletes, then holds at the forfeit


def test_campaign_two_player_contested_resolves_and_advances() -> None:
    # a contested two-player multi-turn game: BLUE dispatches r1, RED blocks r1 each turn -> the adjudicated
    # d100 draw decides delivered/lost; the chain advances byte-identically with 2 COMMAND steps per turn.
    contested = {"BLUE": (REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid" / "dispatch_r1.json").read_bytes(),
                 "RED": (REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid" / "block_r1.json").read_bytes()}
    drivens = camp.run_campaign(drive.INITIAL_STATE, [contested, contested], run_id="c")
    assert len(drivens) == 2
    for i, d in enumerate(drivens):
        slots = {s["calling_slot"] for s in d["llm_steps"]}
        assert slots == {"BLUE", "RED"} and all(s["step_kind"] == "COMMAND" for s in d["llm_steps"])
        terminals = {e["event_type"] for e in d["turn_record"]["event_batch"]}
        assert terminals & {"SUPPLY_DELIVERED", "SUPPLY_LOST"}        # the contest resolved to a terminal
        if i > 0:  # byte-identical head handoff
            assert d["turn_record"]["start_state"]["state_digest"] == \
                   drivens[i - 1]["turn_record"]["resulting_state"]["state_digest"]


def test_campaign_midgame_illegal_forfeit_continues() -> None:
    # an illegal move mid-game (RED issues DISPATCH_SUPPLY, role-action-mismatch) forfeits that slot; the
    # chain does NOT crash and the next turn proceeds from the advanced head.
    legal = {"BLUE": (REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid" / "dispatch_r1.json").read_bytes()}
    illegal_red = {"BLUE": (REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid" / "dispatch_r1.json").read_bytes(),
                   "RED": _tool_use("DISPATCH_SUPPLY", {"quantity": 30, "route": "r1"})}
    drivens = camp.run_campaign(drive.INITIAL_STATE, [legal, illegal_red, legal], run_id="c")
    assert len(drivens) == 3
    red_step = [s for s in drivens[1]["llm_steps"] if s["calling_slot"] == "RED"][0]
    assert red_step["step_kind"] == "ILLEGAL_FORFEIT" and red_step["reject_code"] == "role-action-mismatch"
    # RED forfeited but BLUE's turn-1 dispatch still committed; the chain continued to turn 2
    assert any(c["actor_id"] == "BLUE" for c in drivens[1]["turn_record"]["command_batch"])
    assert drivens[2]["turn_record"]["turn"] == 2


def test_campaign_fog_holds_across_turns() -> None:
    # across the contested chain, BLUE's per-turn view never carries the hidden threshold or RED's block.
    from engine_projection import project_turn_record
    contested = {"BLUE": (REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid" / "dispatch_r1.json").read_bytes(),
                 "RED": (REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid" / "block_r1.json").read_bytes()}
    drivens = camp.run_campaign(drive.INITIAL_STATE, [contested, contested], run_id="c")
    for d in drivens:
        blue_view = project_turn_record("BLUE", d["turn_record"])
        blob = json.dumps(blue_view)
        assert "block_threshold" not in blob and "ROUTE_SECRET" not in blob   # the secret never reaches BLUE
        assert "ROUTE_BLOCK_ATTEMPTED" not in blob                            # BLUE never sees RED's block


# --- "RED matters": both roads blockable, driven end-to-end through the offline pipeline -------------

def _both_blockable() -> dict:
    return {"BLUE": _tool_use("DISPATCH_SUPPLY", {"quantity": 10, "route": "r2"}),
            "RED": _tool_use("BLOCK_ROUTE", {"route": "r2"})}


def test_campaign_both_blockable_r2_is_now_contested() -> None:
    # On a both-blockable start state (route_secret:r2 present), BLUE dispatches r2 and RED blocks r2 ->
    # the r2 contest now DRAWS a d100 and resolves, where the old game would have free-delivered. Seed 0
    # (drive_turn): turn 0 d100 85 -> DELIVERED, turn 1 d100 40 -> LOST (independently RNG-oracle-verified)
    # -- i.e. RED interdicts on the previously-free road. The chain advances byte-identically.
    drivens = camp.run_campaign(drive.both_blockable_state(r2_threshold=50), [_both_blockable()] * 2, run_id="bb")
    assert len(drivens) == 2
    for d in drivens:                                            # both turns: 2 COMMAND steps + one r2 draw
        assert {s["calling_slot"] for s in d["llm_steps"]} == {"BLUE", "RED"}
        assert all(s["step_kind"] == "COMMAND" for s in d["llm_steps"])
        assert len(d["turn_record"]["draw_records"]) == 1
    terms = [next(e["event_type"] for e in d["turn_record"]["event_batch"]
                  if e["event_type"] in ("SUPPLY_DELIVERED", "SUPPLY_LOST")) for d in drivens]
    assert terms == ["SUPPLY_DELIVERED", "SUPPLY_LOST"]          # a contested delivery THEN a contested loss on r2
    assert drivens[1]["turn_record"]["start_state"]["state_digest"] == \
           drivens[0]["turn_record"]["resulting_state"]["state_digest"]   # byte-identical head handoff


def test_campaign_both_blockable_fog_hides_r2_secret() -> None:
    # the new road's hidden threshold (route_secret:r2) must be just as invisible to BOTH players as r1's.
    from engine_projection import project_turn_record
    drivens = camp.run_campaign(drive.both_blockable_state(r2_threshold=50), [_both_blockable()] * 2, run_id="bb")
    for d in drivens:
        for viewer in ("BLUE", "RED"):
            blob = json.dumps(project_turn_record(viewer, d["turn_record"]))
            assert "ROUTE_SECRET" not in blob and "block_threshold" not in blob and "route_secret:r2" not in blob

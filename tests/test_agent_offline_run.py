"""Behavior tests for scripts/agent_offline_run.py (the offline agent drive, WP-A1a).

drive_turn is PURE: hand-authored bytes -> extract -> harness-bound identity -> assemble. The committed
example examples/contested_logistics_agents/ must bind under the provenance gate (the live integration).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BYTES = REPO_ROOT / "tests" / "fixtures" / "agent_bytes"
EXAMPLE = REPO_ROOT / "examples" / "contested_logistics_agents"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import agent_offline_run as drive  # noqa: E402
from canon import canonical_digest  # noqa: E402
from command_extractor import project_semantic  # noqa: E402


def test_drive_turn_produces_a_binding_command_record() -> None:
    out = drive.drive_turn(drive.INITIAL_STATE,
                           {"BLUE": (BYTES / "valid" / "dispatch_r1.json").read_bytes()},
                           run_id="t", turn=0)
    rec = out["turn_record"]
    assert rec["resolver_id"] == "agent_logistics"
    cmd = [c for c in rec["command_batch"] if c["actor_id"] == "BLUE"][0]
    # harness bound the identity (not the model)
    assert cmd["command_id"] == "t:0:BLUE" and cmd["turn"] == 0 and cmd["actor_id"] == "BLUE"
    # the one llm_step binds to the committed command's semantic projection
    step = out["llm_steps"][0]
    assert step["step_kind"] == "COMMAND" and step["calling_slot"] == "BLUE"
    assert step["capture_mode"] == "HAND_AUTHORED_FIXTURE" and step["model"] == "N/A_FIXTURE"
    assert step["extracted_command_digest"] == canonical_digest(project_semantic(cmd))["value"]
    # two content-addressed artifacts (response + request), keyed by their own sha
    assert len(out["artifacts"]) == 2
    assert step["response_sha256"] in out["artifacts"]


def test_drive_turn_forfeit_is_noop() -> None:
    # malformed bytes -> a FORFEIT step + NO command in the batch (the slot resolves NO_OP)
    out = drive.drive_turn(drive.INITIAL_STATE,
                           {"BLUE": (BYTES / "invalid" / "no_command.json").read_bytes()},
                           run_id="t", turn=0)
    assert out["turn_record"]["command_batch"] == []
    step = out["llm_steps"][0]
    assert step["step_kind"] == "FORFEIT" and step["reject_code"] == "no-command"
    assert step["extracted_command_digest"] is None


def _tool_use(action_type: str, params: dict) -> bytes:
    return json.dumps({"role": "assistant", "content": [{"type": "tool_use", "name": "submit_command",
        "input": {"action_type": action_type, "params": params}}]}).encode()


def test_drive_turn_illegal_command_forfeits_to_noop() -> None:
    # WP-A2a: a WELL-FORMED but engine-illegal command (quantity 50 > 30) -> an ILLEGAL_FORFEIT step + NO
    # command in the batch (the slot forfeits, the turn still RESOLVES -- the live-call crash is fixed).
    out = drive.drive_turn(drive.INITIAL_STATE,
                           {"BLUE": _tool_use("DISPATCH_SUPPLY", {"quantity": 50, "route": "r1"})},
                           run_id="t", turn=0)
    assert out["turn_record"]["command_batch"] == []          # forfeited -> no command; turn still resolved
    step = out["llm_steps"][0]
    assert step["step_kind"] == "ILLEGAL_FORFEIT" and step["reject_code"] == "out-of-range"
    assert step["extracted_command_digest"] is not None        # the command WAS extracted, just illegal


def test_drive_turn_wrong_role_forfeits() -> None:
    # RED issuing DISPATCH_SUPPLY (RED may only BLOCK_ROUTE) -> ILLEGAL_FORFEIT role-action-mismatch
    out = drive.drive_turn(drive.INITIAL_STATE,
                           {"RED": _tool_use("DISPATCH_SUPPLY", {"quantity": 30, "route": "r1"})},
                           run_id="t", turn=0)
    assert out["turn_record"]["command_batch"] == []
    step = out["llm_steps"][0]
    assert step["step_kind"] == "ILLEGAL_FORFEIT" and step["reject_code"] == "role-action-mismatch"


def test_commit_turn_writes_record_and_bytes(tmp_path: Path) -> None:
    out = drive.drive_turn(drive.INITIAL_STATE,
                           {"BLUE": (BYTES / "valid" / "dispatch_r1.json").read_bytes()},
                           run_id="t", turn=0)
    drive.commit_turn(tmp_path, out)
    assert (tmp_path / "run" / "turns" / "0000.json").is_file()
    for sha in out["artifacts"]:
        assert (tmp_path / "run" / "llm" / f"{sha}.json").is_file()


def test_committed_example_binds_under_the_gate() -> None:
    # the live integration: the committed example scenario must bind (non-vacuous provenance)
    gate = REPO_ROOT / "scripts" / "validate_agent_provenance.py"
    r = subprocess.run([sys.executable, str(gate), "--scenario-dir", str(EXAMPLE)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "1 step(s) bound" in r.stdout

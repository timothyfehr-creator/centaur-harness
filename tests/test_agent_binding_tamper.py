"""Tampered-binding fail-closed tests (WP-A1a slice 7) — provenance is NOT redundant with replay.

THE LOAD-BEARING PAIR: a SELF-CONSISTENT tamper (a record re-resolved so its events/digests/
transition_input_hash are all internally perfect) is GREEN on validate_turn_replay but RED on
validate_agent_provenance — because only the binding to the RECORDED BYTES catches that the committed
command no longer matches what the bytes extract to. Replay alone cannot see it.

The @heldout probes are authored as the Goodhart split: failure modes the gate was NOT developed against
(a lying stored digest, an edited-but-rehashed byte, a stale extractor version, a non-canon command).
NOTE the disclosed AUTHENTICITY residual: a FULLY self-consistent fabrication (bytes + sha + committed
command + digest all rebuilt to agree) binds green — the gate proves internal consistency, not that the
bytes authentically came from a model. These probes catch PARTIAL tampers, which is the gate's job.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BYTES = REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid"
REPLAY = REPO_ROOT / "scripts" / "validate_turn_replay.py"
PROV = REPO_ROOT / "scripts" / "validate_agent_provenance.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import agent_logistics as al  # noqa: E402
import agent_offline_run as drive  # noqa: E402
import turn_record as tr  # noqa: E402
from agent_logistics import RESOLVER_ID  # noqa: E402
from canon import canonical_digest  # noqa: E402
from command_extractor import extract_command, project_semantic  # noqa: E402

RUN = "t"


def _cmd(route: str) -> dict:
    return {"command_id": f"{RUN}:0:BLUE", "turn": 0, "actor_id": "BLUE",
            "action_type": "DISPATCH_SUPPLY", "params": {"quantity": 30, "route": route}}


def _response_bytes(route: str) -> bytes:
    return json.dumps({"role": "assistant", "content": [
        {"type": "tool_use", "name": "submit_command",
         "input": {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 30, "route": route}}}]}).encode()


def _scenario(tmp: Path, *, committed_command: dict, response_bytes: bytes, step_mut=None) -> Path:
    """A committed single-turn scenario: a (possibly tampered) command + recorded bytes + one llm_step.
    The record is REAL (assemble re-resolves it), so it is internally consistent and replays clean."""
    scn = tmp / "scn"
    (scn / "run" / "turns").mkdir(parents=True)
    (scn / "run" / "llm").mkdir(parents=True)
    out = tr.assemble(turn=0, start_state=drive.INITIAL_STATE, commands=[committed_command], master_seed=0,
                      runtime_fingerprint=drive.FP, successor_slot="run/turns/0001.json", resolver=al)
    assert out["status"] == "resolved"
    tr.commit(out["turn_record"], str(scn / "run" / "turns" / "0000.json"))
    request = drive._request_bytes("BLUE", 0, "v1")
    for b in (response_bytes, request):
        (scn / "run" / "llm" / f"{hashlib.sha256(b).hexdigest()}.json").write_bytes(b)
    res = extract_command(response_bytes)
    digest = canonical_digest(project_semantic(res.command))["value"] if res.ok else None
    step = drive._llm_step("BLUE", 0, RUN, response_bytes, request, digest,
                           None if res.ok else res.reject_code, "v1")
    if step_mut:
        step_mut(step)
    (scn / "run_ledger.yaml").write_text(yaml.safe_dump({"llm_steps": [step]}, sort_keys=False, width=4096))
    return scn


def _replay(scn: Path) -> int:
    return subprocess.run([sys.executable, str(REPLAY), str(scn / "run" / "turns" / "0000.json")],
                          cwd=REPO_ROOT, capture_output=True, text=True).returncode


def _prov(scn: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(PROV), "--scenario-dir", str(scn)],
                          cwd=REPO_ROOT, capture_output=True, text=True)


# --- THE LOAD-BEARING PAIR ---------------------------------------------------------

def test_self_consistent_semantic_tamper_green_on_replay_red_on_provenance(tmp_path: Path) -> None:
    # committed command says r2; the recorded bytes extract r1. The record is re-resolved for r2, so it is
    # internally perfect (replay GREEN) -- but the binding to the bytes catches it (provenance RED).
    scn = _scenario(tmp_path, committed_command=_cmd("r2"), response_bytes=_response_bytes("r1"))
    assert _replay(scn) == 0, "the re-resolved record must pass replay (it is internally consistent)"
    r = _prov(scn)
    assert r.returncode == 1 and "semantic-digest-mismatch" in r.stderr, r.stderr


def test_self_consistent_command_id_tamper_green_on_replay_red_on_provenance(tmp_path: Path) -> None:
    tampered = _cmd("r1")
    tampered["command_id"] = "evil:0:BLUE"   # not the harness-bound f"{run_id}:{turn}:{slot}"
    scn = _scenario(tmp_path, committed_command=tampered, response_bytes=_response_bytes("r1"))
    assert _replay(scn) == 0
    r = _prov(scn)
    assert r.returncode == 1 and "command-id-mismatch" in r.stderr, r.stderr


def test_valid_scenario_is_green_on_both(tmp_path: Path) -> None:
    scn = _scenario(tmp_path, committed_command=_cmd("r1"), response_bytes=_response_bytes("r1"))
    assert _replay(scn) == 0 and _prov(scn).returncode == 0


# --- the Goodhart split (held out from gate development) ----------------------------

@pytest.mark.heldout
def test_heldout_digest_trust_lying_stored_digest(tmp_path: Path) -> None:
    # the attacker tampers the command to r2 AND updates the stored digest to digest(r2); the gate
    # re-extracts from the bytes (r1) and never trusts the stored digest -> caught.
    r1_digest_of_r2 = canonical_digest(project_semantic({"action_type": "DISPATCH_SUPPLY",
                                                         "params": {"quantity": 30, "route": "r2"}}))["value"]
    scn = _scenario(tmp_path, committed_command=_cmd("r2"), response_bytes=_response_bytes("r1"),
                    step_mut=lambda s: s.__setitem__("extracted_command_digest", r1_digest_of_r2))
    r = _prov(scn)
    assert r.returncode == 1 and "recorded-digest-mismatch" in r.stderr, r.stderr


@pytest.mark.heldout
def test_heldout_byte_rehash_edited_bytes_with_updated_sha(tmp_path: Path) -> None:
    # the attacker edits the bytes to extract r2 and updates response_sha256 to match, but leaves the
    # committed command r1 -> Tier-1 passes, but binding to the committed command catches it.
    edited = _response_bytes("r2")
    scn = _scenario(tmp_path, committed_command=_cmd("r1"), response_bytes=edited,
                    step_mut=None)   # _scenario already records sha256(edited) and writes edited bytes
    r = _prov(scn)
    assert r.returncode == 1 and "semantic-digest-mismatch" in r.stderr, r.stderr


@pytest.mark.heldout
def test_heldout_stale_extractor_version_fails_closed(tmp_path: Path) -> None:
    scn = _scenario(tmp_path, committed_command=_cmd("r1"), response_bytes=_response_bytes("r1"),
                    step_mut=lambda s: s.__setitem__("extractor_version", "99"))
    r = _prov(scn)
    assert r.returncode == 2 and "extractor_version" in r.stderr


@pytest.mark.heldout
def test_heldout_non_canon_command_bytes_do_not_bind(tmp_path: Path) -> None:
    # a COMMAND step whose bytes carry a float param: the extractor rejects (non-canon) -> missing-command
    non_canon = json.dumps({"role": "assistant", "content": [
        {"type": "tool_use", "name": "submit_command",
         "input": {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 1.5, "route": "r1"}}}]}).encode()
    # the step claims a COMMAND with a digest, but the bytes won't extract -> the gate flags it
    scn = _scenario(tmp_path, committed_command=_cmd("r1"), response_bytes=_response_bytes("r1"))
    # swap the recorded bytes for the non-canon ones, keeping the recorded sha pointing at them
    (scn / "run" / "llm").mkdir(exist_ok=True)
    sha = hashlib.sha256(non_canon).hexdigest()
    (scn / "run" / "llm" / f"{sha}.json").write_bytes(non_canon)
    doc = yaml.safe_load((scn / "run_ledger.yaml").read_text())
    doc["llm_steps"][0]["response_sha256"] = sha
    (scn / "run_ledger.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, width=4096))
    r = _prov(scn)
    assert r.returncode == 1 and "missing-command" in r.stderr, r.stderr


def test_resolver_id_is_agent_logistics() -> None:
    assert RESOLVER_ID == "agent_logistics"

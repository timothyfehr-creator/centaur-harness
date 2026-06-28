"""Behavior tests for scripts/validate_agent_provenance.py (the H7 binding gate, WP-A1a).

A VALID scenario is built by the REAL machinery (hand-authored bytes -> extract_command -> harness-bound
identity -> turn_record.assemble(resolver=agent_logistics) -> commit + content-addressed bytes + a populated
run_ledger.llm_steps). The gate must bind it. Each INVALID case is a single-field mutation of that valid
scenario and must fail closed with exactly one expected code — proving the binding is load-bearing, not
decorative.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "validate_agent_provenance.py"
AGENT_BYTES = REPO_ROOT / "tests" / "fixtures" / "agent_bytes"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import agent_logistics as al  # noqa: E402
import turn_record as tr  # noqa: E402
from canon import CANON_VERSION, canonical_digest  # noqa: E402
from command_extractor import EXTRACTOR_VERSION, extract_command, project_semantic  # noqa: E402

FP = {"engine_source_hash": "test", "python": "test", "pyyaml_version": "test",
      "serializer_version": "1", "persistence_profile": "test"}
RUN_ID = "demo-001"


def _make_state(as_of_turn: int = 0) -> dict:
    return {"schema_version": "1.0", "state": {"as_of_turn": as_of_turn, "entities": [
        {"id": "blue_supply", "type": "FORCE", "fields": {
            "origin": {"value": 100, "unit": "units"}, "in_transit": {"value": 0, "unit": "units"},
            "delivered": {"value": 0, "unit": "units"}, "loss_sink": {"value": 0, "unit": "units"}}},
        {"id": "route:r1", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": True, "unit": "bool"}}},
        {"id": "route_secret:r1", "type": "ROUTE_SECRET", "fields": {
            "subject_route": {"value": "r1", "unit": "id"},
            "block_threshold": {"value": 73, "unit": "d100"}}}]}}


def _build(tmp_path: Path) -> tuple[Path, dict]:
    """A binding single-turn BLUE-dispatch scenario built by the real machinery."""
    scn = tmp_path / "scn"
    (scn / "run" / "turns").mkdir(parents=True)
    (scn / "run" / "llm").mkdir(parents=True)

    response = (AGENT_BYTES / "valid" / "dispatch_r1.json").read_bytes()
    res = extract_command(response)
    assert res.ok
    cmd = {"command_id": f"{RUN_ID}:0:BLUE", "turn": 0, "actor_id": "BLUE",
           "action_type": res.command["action_type"], "params": res.command["params"]}
    out = tr.assemble(turn=0, start_state=_make_state(), commands=[cmd], master_seed=0,
                      runtime_fingerprint=FP, successor_slot="run/turns/0001.json", resolver=al)
    assert out["status"] == "resolved"
    tr.commit(out["turn_record"], str(scn / "run" / "turns" / "0000.json"))

    resp_sha = hashlib.sha256(response).hexdigest()
    (scn / "run" / "llm" / f"{resp_sha}.json").write_bytes(response)
    request = json.dumps({"model": "x", "tools": ["submit_command"]}).encode()
    req_sha = hashlib.sha256(request).hexdigest()
    (scn / "run" / "llm" / f"{req_sha}.json").write_bytes(request)

    step = {
        "schema_version": "1.0", "run_id": RUN_ID, "turn": 0, "recorded_turn": 0,
        "calling_slot": "BLUE", "command_id": f"{RUN_ID}:0:BLUE", "step_kind": "COMMAND",
        "capture_mode": "HAND_AUTHORED_FIXTURE", "provider": "anthropic",
        "model": "N/A_FIXTURE", "model_version": "N/A_FIXTURE", "served_model": "N/A_FIXTURE",
        "sampling": "PROVIDER_DEFAULT_NO_SEED", "prompt_version": "v1",
        "extractor_version": EXTRACTOR_VERSION, "canon_version": CANON_VERSION,
        "response_sha256": resp_sha, "request_envelope_sha256": req_sha,
        "extracted_command_digest": canonical_digest(project_semantic(res.command))["value"],
        "reject_code": None, "as_of": "2026-06-27",
    }
    _write_ledger(scn, [step])
    return scn, step


def _write_ledger(scn: Path, steps: list) -> None:
    (scn / "run_ledger.yaml").write_text(
        yaml.safe_dump({"llm_steps": steps}, sort_keys=False, width=4096), encoding="utf-8")


def _rec_path(scn: Path) -> Path:
    return scn / "run" / "turns" / "0000.json"


def _mutate_record(scn: Path, fn) -> None:
    rec = json.loads(_rec_path(scn).read_text())
    fn(rec)
    _rec_path(scn).write_text(json.dumps(rec), encoding="utf-8")


def _run(scn: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(GATE), "--scenario-dir", str(scn)],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def _findings(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.lstrip().startswith("- ")]


def test_valid_scenario_binds(tmp_path: Path) -> None:
    scn, _ = _build(tmp_path)
    r = _run(scn)
    assert r.returncode == 0, r.stderr
    assert "1 step(s) bound" in r.stdout


def test_vacuous_pass_on_null_llm_steps(tmp_path: Path) -> None:
    scn = tmp_path / "scn"
    scn.mkdir()
    (scn / "run_ledger.yaml").write_text("llm_steps: null\n")
    assert _run(scn).returncode == 0


def _expect_one(scn: Path, code: str) -> None:
    r = _run(scn)
    assert r.returncode == 1, f"expected findings; stdout={r.stdout} stderr={r.stderr}"
    fs = _findings(r.stderr)
    assert len(fs) == 1, f"expected one finding, got {fs}"
    assert code in fs[0], f"expected {code}, got {fs[0]!r}"


def test_tampered_semantic_command(tmp_path: Path) -> None:
    scn, _ = _build(tmp_path)
    _mutate_record(scn, lambda rec: rec["command_batch"][0]["params"].__setitem__("route", "r2"))
    _expect_one(scn, "semantic-digest-mismatch")


def test_tampered_command_id(tmp_path: Path) -> None:
    scn, _ = _build(tmp_path)
    _mutate_record(scn, lambda rec: rec["command_batch"][0].__setitem__("command_id", "evil:0:BLUE"))
    _expect_one(scn, "command-id-mismatch")


def test_mis_bound_actor_is_slot_count(tmp_path: Path) -> None:
    scn, _ = _build(tmp_path)
    _mutate_record(scn, lambda rec: rec["command_batch"][0].__setitem__("actor_id", "RED"))
    _expect_one(scn, "slot-command-count")


def test_lying_recorded_digest(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    step["extracted_command_digest"] = "b" * 64  # a valid-looking but wrong digest
    _write_ledger(scn, [step])
    _expect_one(scn, "recorded-digest-mismatch")


def test_edited_response_bytes(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    artifact = scn / "run" / "llm" / f"{step['response_sha256']}.json"
    artifact.write_bytes(artifact.read_bytes() + b" ")  # bytes changed, recorded sha unchanged
    _expect_one(scn, "response-bytes-tampered")


def test_missing_artifact(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    (scn / "run" / "llm" / f"{step['response_sha256']}.json").unlink()
    _expect_one(scn, "artifact-missing")


def test_unknown_key(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    step["smuggled"] = "x"
    _write_ledger(scn, [step])
    _expect_one(scn, "unknown-key")


def test_bad_enum_calling_slot(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    step["calling_slot"] = "GREEN"
    _write_ledger(scn, [step])
    _expect_one(scn, "invalid-enum")


def test_fixture_model_claim(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    step["served_model"] = "claude-opus-4-8"  # a fixture cannot claim a served model
    _write_ledger(scn, [step])
    _expect_one(scn, "fixture-model-claim")


def test_canon_version_mismatch(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    step["canon_version"] = "canon-v2"
    _write_ledger(scn, [step])
    _expect_one(scn, "canon-version-mismatch")


def test_command_step_with_reject_code(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    step["reject_code"] = "no-command"  # a COMMAND must have reject_code null
    _write_ledger(scn, [step])
    _expect_one(scn, "digest-presence-mismatch")


def test_stale_extractor_version_fails_closed(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    step["extractor_version"] = "99"  # a version this build cannot reproduce
    _write_ledger(scn, [step])
    r = _run(scn)
    assert r.returncode == 2 and "extractor_version" in r.stderr


def test_recorded_turn_mismatch(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)
    step["recorded_turn"] = 7  # != turn 0
    _write_ledger(scn, [step])
    _expect_one(scn, "recorded-turn-mismatch")


def test_uncovered_command_has_no_backing_step(tmp_path: Path) -> None:
    # the converse binding: a FABRICATED command with no llm_step must be caught (coverage)
    scn, _ = _build(tmp_path)
    _mutate_record(scn, lambda rec: rec["command_batch"].append(
        {"command_id": f"{RUN_ID}:0:RED", "turn": 0, "actor_id": "RED",
         "action_type": "BLOCK_ROUTE", "params": {"route": "r1"}}))
    _expect_one(scn, "uncovered-command")


def test_duplicate_step_for_one_slot_is_rejected(tmp_path: Path) -> None:
    # cardinality: a padded log (two COMMAND steps for the same (turn, slot)) must be rejected
    scn, step = _build(tmp_path)
    _write_ledger(scn, [step, dict(step)])
    _expect_one(scn, "duplicate-step")

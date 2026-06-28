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
from engine_projection import project_turn_record  # noqa: E402
from prompt_templates import A1B_PROMPT_VERSION, canonical_request_bytes  # noqa: E402

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


def _make_state_with_origin(origin: int) -> dict:
    """_make_state with a different PUBLIC blue origin (a FORCE field that survives projection), so the fog
    view -- and thus the rendered request -- differs. Used to forge a self-consistent request tamper."""
    s = _make_state()
    s["state"]["entities"][0]["fields"]["origin"]["value"] = origin
    return s


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


def _expect_code(scn: Path, code: str) -> None:
    """A single FAULT may trip more than one finding (e.g. all three LIVE model fields); assert the expected
    code is present + exit 1 (less strict than _expect_one, for multi-finding faults)."""
    r = _run(scn)
    assert r.returncode == 1, f"expected findings; stdout={r.stdout} stderr={r.stderr}"
    assert any(code in f for f in _findings(r.stderr)), f"expected {code} in {_findings(r.stderr)}"


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


# --- Tier-3 request-envelope binding (WP-A1b §2.3-2.4) -----------------------------------------------

def _build_tier3(tmp_path: Path, *, prompt_version: str = A1B_PROMPT_VERSION) -> tuple[Path, dict]:
    """A binding single-turn scenario whose request envelope is the TEMPLATE render (Tier-3) from BLUE's
    decision-head fog view -- i.e. exactly what the (deferred) live producer will commit. Mirrors _build
    but swaps the offline synthetic request for canonical_request_bytes(prompt_version, view)."""
    scn = tmp_path / "scn"
    (scn / "run" / "turns").mkdir(parents=True)
    (scn / "run" / "llm").mkdir(parents=True)
    start = _make_state()
    response = (AGENT_BYTES / "valid" / "dispatch_r1.json").read_bytes()
    res = extract_command(response)
    assert res.ok
    cmd = {"command_id": f"{RUN_ID}:0:BLUE", "turn": 0, "actor_id": "BLUE",
           "action_type": res.command["action_type"], "params": res.command["params"]}
    out = tr.assemble(turn=0, start_state=start, commands=[cmd], master_seed=0,
                      runtime_fingerprint=FP, successor_slot="run/turns/0001.json", resolver=al)
    assert out["status"] == "resolved"
    tr.commit(out["turn_record"], str(scn / "run" / "turns" / "0000.json"))
    resp_sha = hashlib.sha256(response).hexdigest()
    (scn / "run" / "llm" / f"{resp_sha}.json").write_bytes(response)
    view = project_turn_record("BLUE", {"turn": 0, "resulting_state": start, "event_batch": []})
    request = canonical_request_bytes(prompt_version, view)
    req_sha = hashlib.sha256(request).hexdigest()
    (scn / "run" / "llm" / f"{req_sha}.json").write_bytes(request)
    step = {
        "schema_version": "1.0", "run_id": RUN_ID, "turn": 0, "recorded_turn": 0,
        "calling_slot": "BLUE", "command_id": f"{RUN_ID}:0:BLUE", "step_kind": "COMMAND",
        "capture_mode": "HAND_AUTHORED_FIXTURE", "provider": "anthropic",
        "model": "N/A_FIXTURE", "model_version": "N/A_FIXTURE", "served_model": "N/A_FIXTURE",
        "sampling": "PROVIDER_DEFAULT_NO_SEED", "prompt_version": prompt_version,
        "extractor_version": EXTRACTOR_VERSION, "canon_version": CANON_VERSION,
        "response_sha256": resp_sha, "request_envelope_sha256": req_sha,
        "extracted_command_digest": canonical_digest(project_semantic(res.command))["value"],
        "reject_code": None, "as_of": "2026-06-27",
    }
    _write_ledger(scn, [step])
    return scn, step


def test_tier3_template_request_binds(tmp_path: Path) -> None:
    scn, _ = _build_tier3(tmp_path)
    r = _run(scn)
    assert r.returncode == 0, r.stderr


def test_tier3_self_consistent_request_tamper_is_caught(tmp_path: Path) -> None:
    # the load-bearing proof Tier-3 adds over Tier-1: a request whose bytes RE-HASH fine but are NOT the
    # render of the authorized template over the authorized fog view. We swap in a DIFFERENT (self-consistent)
    # envelope -- the template applied to a different public state -- and point the step at its sha.
    scn, step = _build_tier3(tmp_path)
    other_view = project_turn_record("BLUE", {"turn": 0,
        "resulting_state": _make_state_with_origin(7), "event_batch": []})
    tampered = canonical_request_bytes(A1B_PROMPT_VERSION, other_view)
    tampered_sha = hashlib.sha256(tampered).hexdigest()
    (scn / "run" / "llm" / f"{tampered_sha}.json").write_bytes(tampered)   # bytes <-> sha self-consistent
    step["request_envelope_sha256"] = tampered_sha
    _write_ledger(scn, [step])
    _expect_one(scn, "request-envelope-binding-mismatch")   # Tier-1 re-hash passes; Tier-3 re-render catches it


def test_tier3_unknown_prompt_version_fails_closed(tmp_path: Path) -> None:
    scn, step = _build_tier3(tmp_path)
    step["prompt_version"] = "ptmpl-0000000000000000"   # not registered, not the integrity-only sentinel
    _write_ledger(scn, [step])
    r = _run(scn)
    assert r.returncode == 2 and "fail closed" in r.stderr


def test_tier3_registered_but_unapproved_fails_closed(tmp_path: Path, monkeypatch) -> None:
    # "registered != audited" (§2.2 leg 1): pretend A1B is registered but NOT on the approved allowlist;
    # the binding must fail closed (exit 2), proving a merely-registered template is insufficient.
    import validate_agent_provenance as vap
    scn, step = _build_tier3(tmp_path)
    monkeypatch.setattr(vap, "APPROVED_PROMPT_VERSIONS", ())
    rc, payload = vap._envelope_binding(step, scn, "where")
    assert rc == 2 and "APPROVED" in payload


def test_tier3_malformed_record_fails_closed_not_traceback(tmp_path: Path) -> None:
    # robustness (slice-4 review R-2): a committed record the re-render cannot read (here: start_state
    # stripped) must fail CLOSED (exit 2) with a clean message on the template path -- not a raw traceback.
    scn, _ = _build_tier3(tmp_path)
    _mutate_record(scn, lambda rec: rec.pop("start_state", None))
    r = _run(scn)
    assert r.returncode == 2 and "fail closed" in r.stderr and "Traceback" not in r.stderr


def test_v1_offline_step_is_integrity_only_no_rerender(tmp_path: Path) -> None:
    # the reserved "v1" sentinel stays Tier-1: _build's request is a NON-template body ({"model":"x",...});
    # if the gate wrongly tried to re-render it as a template it would fail, so a green result proves no
    # re-render is attempted for the offline synthetic envelope.
    scn, _ = _build(tmp_path)
    r = _run(scn)
    assert r.returncode == 0, r.stderr


# --- LIVE-capture provenance (WP-A1b §1.8 / §3.2 / §3.3) --------------------------------------------

_LIVE_FIELDS = {"provider_request_id": "req_abc123def456", "anthropic_api_version": "2023-06-01",
                "model_id_stability": "PROVIDER_DOCUMENTED_PINNED_MODEL_ID_INFRA_MAY_CHANGE",
                "authenticity": "RUNNER_ATTESTED_NOT_PROVEN"}


def _build_live(tmp_path: Path, *, served: str = "claude-opus-4-8", body_model: str | None = None) -> tuple[Path, dict]:
    """A binding LIVE single-turn scenario: capture_mode=LIVE, real model fields, the LIVE audit/disclosure
    scalars, a TEMPLATE-rendered request (Tier-3), and a redacted response body whose own `model` field is
    body_model (defaults to `served`, the honest case)."""
    from response_redact import redact
    scn = tmp_path / "scn"
    (scn / "run" / "turns").mkdir(parents=True)
    (scn / "run" / "llm").mkdir(parents=True)
    start = _make_state()
    wire = json.dumps({"role": "assistant", "model": body_model or served, "stop_reason": "tool_use",
        "id": "msg_x", "usage": {"input_tokens": 50, "output_tokens": 12}, "content": [
        {"type": "tool_use", "name": "submit_command",
         "input": {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 30, "route": "r1"}}}]}).encode()
    response = redact(wire)
    res = extract_command(response)
    assert res.ok
    cmd = {"command_id": f"{RUN_ID}:0:BLUE", "turn": 0, "actor_id": "BLUE",
           "action_type": res.command["action_type"], "params": res.command["params"]}
    out = tr.assemble(turn=0, start_state=start, commands=[cmd], master_seed=0,
                      runtime_fingerprint=FP, successor_slot="run/turns/0001.json", resolver=al)
    assert out["status"] == "resolved"
    tr.commit(out["turn_record"], str(scn / "run" / "turns" / "0000.json"))
    resp_sha = hashlib.sha256(response).hexdigest()
    (scn / "run" / "llm" / f"{resp_sha}.json").write_bytes(response)
    view = project_turn_record("BLUE", {"turn": 0, "resulting_state": start, "event_batch": []})
    request = canonical_request_bytes(A1B_PROMPT_VERSION, view)
    req_sha = hashlib.sha256(request).hexdigest()
    (scn / "run" / "llm" / f"{req_sha}.json").write_bytes(request)
    step = {
        "schema_version": "1.0", "run_id": RUN_ID, "turn": 0, "recorded_turn": 0, "calling_slot": "BLUE",
        "command_id": f"{RUN_ID}:0:BLUE", "step_kind": "COMMAND", "capture_mode": "LIVE",
        "provider": "anthropic", "model": served, "model_version": served, "served_model": served,
        "sampling": "PROVIDER_DEFAULT_NO_SEED", "prompt_version": A1B_PROMPT_VERSION,
        "extractor_version": EXTRACTOR_VERSION, "canon_version": CANON_VERSION,
        "response_sha256": resp_sha, "request_envelope_sha256": req_sha,
        "extracted_command_digest": canonical_digest(project_semantic(res.command))["value"],
        "reject_code": None, "as_of": "2026-06-28", **_LIVE_FIELDS,
    }
    _write_ledger(scn, [step])
    return scn, step


def test_live_step_binds(tmp_path: Path) -> None:
    scn, _ = _build_live(tmp_path)
    r = _run(scn)
    assert r.returncode == 0, r.stderr


def test_live_model_claim_fixture_sentinel_rejected(tmp_path: Path) -> None:
    scn, _ = _build_live(tmp_path, served="N/A_FIXTURE", body_model="N/A_FIXTURE")  # LIVE can't claim the fixture id
    _expect_code(scn, "live-model-claim")


def test_live_missing_request_id_rejected(tmp_path: Path) -> None:
    scn, step = _build_live(tmp_path)
    step.pop("provider_request_id")
    _write_ledger(scn, [step])
    _expect_code(scn, "missing-request-id")


def test_live_served_model_drift_rejected(tmp_path: Path) -> None:
    scn, step = _build_live(tmp_path)
    step["served_model"] = "claude-sonnet-4-6"   # served != requested -> would be EXCLUDED, never committed
    _write_ledger(scn, [step])
    _expect_code(scn, "served-model-drift")


def test_live_model_binding_to_bytes(tmp_path: Path) -> None:
    # the committed response body's own model field must equal served_model/model (§1.8)
    scn, _ = _build_live(tmp_path, served="claude-opus-4-8", body_model="claude-sonnet-4-6")
    _expect_code(scn, "live-model-binding-mismatch")


def test_live_requires_template_pv_not_v1(tmp_path: Path) -> None:
    scn, step = _build_live(tmp_path)
    step["prompt_version"] = "v1"   # the offline integrity-only sentinel is forbidden under LIVE (R-1)
    _write_ledger(scn, [step])
    _expect_code(scn, "live-integrity-only-pv")


def test_fixture_must_not_carry_live_fields(tmp_path: Path) -> None:
    scn, step = _build(tmp_path)   # a HAND_AUTHORED_FIXTURE step
    step["provider_request_id"] = "req_borrowed"   # a fixture can't borrow LIVE provenance
    _write_ledger(scn, [step])
    _expect_code(scn, "fixture-live-field")

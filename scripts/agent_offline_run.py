#!/usr/bin/env python3
"""Offline agent drive (WP-A1a) — wire the strict extractor into the engine seam, zero network.

This is the substrate's single turn driver: given HAND-AUTHORED response bytes standing in for each
player's model output, it extracts the SEMANTIC command, the HARNESS binds the identity
(command_id/turn/actor_id — never the model), and `turn_record.assemble(resolver=agent_logistics)`
referees. The committed artifacts are a turn record (run/turns/), the content-addressed raw bytes
(run/llm/), and a non-causal `llm_steps` provenance list in run_ledger.yaml — all bound by
`validate_agent_provenance.py`. No model is ever called; replay re-runs the engine on the recorded bytes.

A slot whose bytes do not extract exactly one well-formed command FORFEITS (recorded, auditable) and
resolves via a predeclared NO_OP (it contributes no command to the batch — an empty turn is legal).

Run as a script, it (re)generates the committed example scenario examples/contested_logistics_agents/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import agent_logistics as al  # noqa: E402
import turn_record as tr  # noqa: E402
from canon import CANON_VERSION, canonical_digest  # noqa: E402
from command_extractor import EXTRACTOR_VERSION, extract_command, project_semantic  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO = REPO_ROOT / "examples" / "contested_logistics_agents"

# The standard contested-logistics turn-0 typed state (mirrors examples/contested_logistics_abstract).
INITIAL_STATE = {"schema_version": "1.0", "state": {"as_of_turn": 0, "entities": [
    {"id": "blue_supply", "type": "FORCE", "fields": {
        "origin": {"value": 100, "unit": "units"}, "in_transit": {"value": 0, "unit": "units"},
        "delivered": {"value": 0, "unit": "units"}, "loss_sink": {"value": 0, "unit": "units"}}},
    {"id": "route:r1", "type": "ROUTE", "fields": {
        "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": True, "unit": "bool"}}},
    {"id": "route:r2", "type": "ROUTE", "fields": {
        "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": False, "unit": "bool"}}},
    {"id": "route_secret:r1", "type": "ROUTE_SECRET", "fields": {
        "subject_route": {"value": "r1", "unit": "id"},
        "block_threshold": {"value": 73, "unit": "d100"}}}]}}

FP = {"engine_source_hash": "offline-fixture", "python": "fixture", "pyyaml_version": "fixture",
      "serializer_version": "1", "persistence_profile": "fixture"}


def _request_bytes(slot: str, turn: int, prompt_version: str) -> bytes:
    """A minimal synthetic request envelope (integrity-only offline; the prompt<->envelope binding
    re-render is WP-A1b). Deterministic so the hash is stable."""
    return json.dumps({"prompt_version": prompt_version, "calling_slot": slot, "turn": turn},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _llm_step(slot: str, turn: int, run_id: str, response: bytes, request: bytes,
              extracted_digest: str | None, reject_code: str | None, prompt_version: str) -> dict:
    """One flat all-scalar llm_step (HAND_AUTHORED_FIXTURE; see schemas/llm_step.schema.md)."""
    return {
        "schema_version": "1.0", "run_id": run_id, "turn": turn, "recorded_turn": turn,
        "calling_slot": slot, "command_id": f"{run_id}:{turn}:{slot}",
        "step_kind": "COMMAND" if reject_code is None else "FORFEIT",
        "capture_mode": "HAND_AUTHORED_FIXTURE", "provider": "anthropic",
        "model": "N/A_FIXTURE", "model_version": "N/A_FIXTURE", "served_model": "N/A_FIXTURE",
        "sampling": "PROVIDER_DEFAULT_NO_SEED", "prompt_version": prompt_version,
        "extractor_version": EXTRACTOR_VERSION, "canon_version": CANON_VERSION,
        "response_sha256": hashlib.sha256(response).hexdigest(),
        "request_envelope_sha256": hashlib.sha256(request).hexdigest(),
        "extracted_command_digest": extracted_digest, "reject_code": reject_code,
        "as_of": "2026-06-27",
    }


def drive_turn(start_state: dict, byte_by_slot: dict, *, run_id: str, turn: int,
               prompt_version: str = "v1") -> dict:
    """Drive ONE turn from per-slot response bytes. PURE (no I/O). Returns {turn_record, llm_steps,
    artifacts}: artifacts maps sha256 -> raw bytes (response + request, content-addressed)."""
    commands: list = []
    steps: list = []
    artifacts: dict = {}
    for slot in ("BLUE", "RED"):                      # canonical order; the engine re-sorts anyway
        if slot not in byte_by_slot:
            continue
        response = byte_by_slot[slot]
        request = _request_bytes(slot, turn, prompt_version)
        artifacts[hashlib.sha256(response).hexdigest()] = response
        artifacts[hashlib.sha256(request).hexdigest()] = request
        res = extract_command(response)
        if res.ok:
            commands.append({"command_id": f"{run_id}:{turn}:{slot}", "turn": turn, "actor_id": slot,
                             "action_type": res.command["action_type"], "params": res.command["params"]})
            digest = canonical_digest(project_semantic(res.command))["value"]
            steps.append(_llm_step(slot, turn, run_id, response, request, digest, None, prompt_version))
        else:                                          # FORFEIT -> NO_OP (no command in the batch)
            steps.append(_llm_step(slot, turn, run_id, response, request, None, res.reject_code, prompt_version))
    out = tr.assemble(turn=turn, start_state=start_state, commands=commands, master_seed=0,
                      runtime_fingerprint=FP, successor_slot=f"run/turns/{turn + 1:04d}.json", resolver=al)
    if out["status"] != "resolved":
        raise SystemExit(f"turn {turn} rejected: {out.get('rejections')}")
    return {"turn_record": out["turn_record"], "llm_steps": steps, "artifacts": artifacts}


def commit_turn(scenario_dir: Path, driven: dict) -> None:
    """Write the turn record (run/turns/) + the content-addressed bytes (run/llm/). Idempotent-or-fail."""
    rec = driven["turn_record"]
    (scenario_dir / "run" / "turns").mkdir(parents=True, exist_ok=True)
    (scenario_dir / "run" / "llm").mkdir(parents=True, exist_ok=True)
    tr.commit(rec, str(scenario_dir / "run" / "turns" / f"{rec['turn']:04d}.json"))
    for sha, raw in driven["artifacts"].items():
        (scenario_dir / "run" / "llm" / f"{sha}.json").write_bytes(raw)


def write_ledger_with_steps(scenario_dir: Path, all_steps: list) -> int:
    """--write the run-ledger (pins declared inputs), then inject the populated llm_steps with the same
    pinned serializer. Reuses validate_run_ledger so the lockfile discipline is identical."""
    import validate_run_ledger as vrl  # noqa: PLC0415
    import yaml  # noqa: PLC0415
    ledger = scenario_dir / "run_ledger.yaml"
    rc = vrl.main([str(ledger), "--scenario-dir", str(scenario_dir), "--write"])
    if rc != 0:
        return rc
    doc = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    doc["llm_steps"] = all_steps
    ledger.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False,
                                     allow_unicode=True, width=4096), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_offline_run.py",
                                     description="(Re)generate the offline agent example (single BLUE turn).")
    parser.add_argument("--scenario-dir", default=str(SCENARIO))
    parser.add_argument("--run-id", default="contested-agents-001")
    args = parser.parse_args(argv)
    scn = Path(args.scenario_dir).resolve()
    bytes_dir = REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid"
    driven = drive_turn(INITIAL_STATE, {"BLUE": (bytes_dir / "dispatch_r1.json").read_bytes()},
                        run_id=args.run_id, turn=0)
    commit_turn(scn, driven)
    rc = write_ledger_with_steps(scn, driven["llm_steps"])
    if rc != 0:
        return rc
    print(f"drove 1 turn into {scn.name}: {len(driven['llm_steps'])} llm_step(s), "
          f"{len(driven['artifacts'])} byte artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import agent_logistics as al  # noqa: E402
import turn_record as tr  # noqa: E402
from canon import CANON_VERSION, canonical_digest  # noqa: E402
from command_extractor import EXTRACTOR_VERSION, extract_command, project_semantic  # noqa: E402
from response_redact import redact  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO = REPO_ROOT / "examples" / "contested_logistics_agents"
SCENARIO_2P = REPO_ROOT / "examples" / "contested_logistics_agents_2p"

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


def both_blockable_state(*, origin: int = 100, r1_threshold: int = 73, r2_threshold: int = 50) -> dict:
    """INITIAL_STATE recast as the 'RED matters' game: route:r2 becomes public-blockable and gains a
    route_secret:r2 (an ASSUMED, ILLUSTRATIVE hidden threshold), so BOTH roads are contestable -- a real
    BLUE-vs-RED guessing duel. Blockability is presence-derived (resolver.block_thresholds), so old
    scenarios (which carry no route_secret:r2) are entirely unaffected. route_secret:r2 is a ROUTE_SECRET,
    hence adjudicator-only and fog-filtered like route_secret:r1."""
    s = copy.deepcopy(INITIAL_STATE)
    ents = s["state"]["entities"]
    ents[0]["fields"]["origin"]["value"] = origin                       # blue_supply
    ents[2]["fields"]["blockable"]["value"] = True                      # route:r2 now blockable (public)
    ents[3]["fields"]["block_threshold"]["value"] = r1_threshold        # route_secret:r1 (adjudicator-only)
    ents.append({"id": "route_secret:r2", "type": "ROUTE_SECRET", "fields": {
        "subject_route": {"value": "r2", "unit": "id"},
        "block_threshold": {"value": r2_threshold, "unit": "d100"}}})   # adjudicator-only
    return s

FP = {"engine_source_hash": "offline-fixture", "python": "fixture", "pyyaml_version": "fixture",
      "serializer_version": "1", "persistence_profile": "fixture"}


def _request_bytes(slot: str, turn: int, prompt_version: str, correction: str | None = None) -> bytes:
    """A minimal synthetic request envelope (integrity-only offline; the prompt<->envelope binding
    re-render is WP-A1b). Deterministic so the hash is stable. ``correction`` (a retry's reject code) is
    added only when set, so a non-retry attempt's bytes are byte-identical to the pre-retry producer."""
    body: dict = {"prompt_version": prompt_version, "calling_slot": slot, "turn": turn}
    if correction is not None:
        body["correction"] = correction
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def classify_attempt(slot: str, turn: int, run_id: str, start_state: dict, response: bytes,
                     request: bytes) -> dict:
    """Extract + classify ONE attempt's (already-redacted) bytes into a disposition. Shared by the offline
    and live drives. Returns {kind, command, digest, reject, response, request} where kind is
    COMMAND | FORFEIT | ILLEGAL_FORFEIT (the same three-way the step builder pins)."""
    res = extract_command(response)
    if not res.ok:                                        # not well-formed -> FORFEIT
        return {"kind": "FORFEIT", "command": None, "digest": None, "reject": res.reject_code,
                "response": response, "request": request}
    cmd = {"command_id": f"{run_id}:{turn}:{slot}", "turn": turn, "actor_id": slot,
           "action_type": res.command["action_type"], "params": res.command["params"]}
    digest = canonical_digest(project_semantic(res.command))["value"]
    legality = al.command_legality(cmd, start_state)      # the engine's verdict on the HARNESS-BOUND command
    if legality is None:                                  # legal -> COMMAND
        return {"kind": "COMMAND", "command": cmd, "digest": digest, "reject": None,
                "response": response, "request": request}
    return {"kind": "ILLEGAL_FORFEIT", "command": None, "digest": digest, "reject": legality,  # well-formed but illegal
            "response": response, "request": request}


def run_slot_attempts(slot: str, turn: int, run_id: str, start_state: dict, fetch, max_retries: int) -> dict | None:
    """The SHARED retry loop for one slot (network-free; any network lives inside ``fetch``).
    ``fetch(attempt_idx, correction) -> (redacted_response_bytes, request_bytes) | None`` -- None means no
    attempt is available (offline list exhausted, or the live spend cap was hit). Each rejected order is
    re-asked with ``correction = its reject code`` up to ``max_retries`` times; the loop STOPS at the first
    legal command. Returns {decisive, priors} where decisive = the first COMMAND attempt (else the last
    attempt) and priors = the rejected attempts before it; or None if the slot produced no attempt at all."""
    made: list = []
    correction: str | None = None
    for idx in range(max_retries + 1):
        rv = fetch(idx, correction)
        if rv is None:
            break
        response, request = rv
        a = classify_attempt(slot, turn, run_id, start_state, response, request)
        a["correction"] = correction
        made.append(a)
        if a["kind"] == "COMMAND":
            break
        correction = a["reject"]                          # hand the public reason back on the next attempt
    if not made:
        return None
    dec_idx = next((i for i, a in enumerate(made) if a["kind"] == "COMMAND"), len(made) - 1)
    return {"decisive": made[dec_idx], "priors": made[:dec_idx]}


def _prior_attempt(a: dict) -> dict:
    """A rejected prior attempt's NON-binding (but gate-verified) audit record (see schemas/llm_step.schema.md)."""
    return {"response_sha256": hashlib.sha256(a["response"]).hexdigest(),
            "request_envelope_sha256": hashlib.sha256(a["request"]).hexdigest(),
            "attempt_kind": a["kind"], "reject_code": a["reject"], "correction": a["correction"]}


def _llm_step(slot: str, turn: int, run_id: str, response: bytes, request: bytes,
              extracted_digest: str | None, reject_code: str | None, prompt_version: str,
              *, correction: str | None = None, prior_attempts: list | None = None) -> dict:
    """One llm_step (HAND_AUTHORED_FIXTURE; see schemas/llm_step.schema.md). ``correction`` /
    ``prior_attempts`` (WP-A2 retry) are OMITTED when absent, so a no-retry step is byte-identical to the
    pre-retry producer and every committed scenario binds unchanged."""
    step = {
        "schema_version": "1.0", "run_id": run_id, "turn": turn, "recorded_turn": turn,
        "calling_slot": slot, "command_id": f"{run_id}:{turn}:{slot}",
        # disposition by (digest, reject_code): COMMAND (legal), FORFEIT (no well-formed command),
        # ILLEGAL_FORFEIT (a well-formed command the engine ruled illegal -> the slot forfeits).
        "step_kind": ("COMMAND" if extracted_digest is not None and reject_code is None
                      else "ILLEGAL_FORFEIT" if extracted_digest is not None else "FORFEIT"),
        "capture_mode": "HAND_AUTHORED_FIXTURE", "provider": "anthropic",
        "model": "N/A_FIXTURE", "model_version": "N/A_FIXTURE", "served_model": "N/A_FIXTURE",
        "sampling": "PROVIDER_DEFAULT_NO_SEED", "prompt_version": prompt_version,
        "extractor_version": EXTRACTOR_VERSION, "canon_version": CANON_VERSION,
        "response_sha256": hashlib.sha256(response).hexdigest(),
        "request_envelope_sha256": hashlib.sha256(request).hexdigest(),
        "extracted_command_digest": extracted_digest, "reject_code": reject_code,
        "as_of": "2026-06-27",
    }
    if correction is not None:           # this attempt was a retry prompted by a prior reject (a public code)
        step["correction"] = correction
    if prior_attempts:                   # the rejected attempts before the decisive one (non-binding, gate-verified)
        step["prior_attempts"] = prior_attempts
    return step


def drive_turn(start_state: dict, byte_by_slot: dict, *, run_id: str, turn: int,
               prompt_version: str = "v1") -> dict:
    """Drive ONE turn from per-slot response bytes. PURE (no I/O). Returns {turn_record, llm_steps,
    artifacts}: artifacts maps sha256 -> raw bytes (response + request, content-addressed).

    Each slot's value is EITHER a single bytes (one attempt, no retry -- byte-identical to the pre-retry
    producer) OR a LIST of attempt bytes (WP-A2 retry: attempt 0, then corrected retries). The shared retry
    loop stops at the first legal command; the DECISIVE attempt binds the llm_step, the rejected priors
    become its (gate-verified) ``prior_attempts``."""
    commands: list = []
    steps: list = []
    artifacts: dict = {}
    for slot in ("BLUE", "RED"):                      # canonical order; the engine re-sorts anyway
        if slot not in byte_by_slot:
            continue
        raw = byte_by_slot[slot]
        attempts = [raw] if isinstance(raw, (bytes, bytearray)) else list(raw)   # single blob == a 1-attempt slot

        def fetch(idx: int, correction: str | None, _attempts=attempts, _slot=slot):
            if idx >= len(_attempts):
                return None
            # redact at SOURCE before hashing/committing (WP-A1b); the request carries the retry correction
            return (redact(_attempts[idx]), _request_bytes(_slot, turn, prompt_version, correction))

        res = run_slot_attempts(slot, turn, run_id, start_state, fetch, max_retries=len(attempts) - 1)
        if res is None:
            continue
        dec, priors = res["decisive"], res["priors"]
        for a in (dec, *priors):                      # content-address EVERY attempt's response + request
            artifacts[hashlib.sha256(a["response"]).hexdigest()] = a["response"]
            artifacts[hashlib.sha256(a["request"]).hexdigest()] = a["request"]
        if dec["command"] is not None:
            commands.append(dec["command"])
        steps.append(_llm_step(slot, turn, run_id, dec["response"], dec["request"], dec["digest"],
                               dec["reject"], prompt_version, correction=dec["correction"],
                               prior_attempts=[_prior_attempt(a) for a in priors]))
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
                                     description="(Re)generate an offline agent example (single turn).")
    parser.add_argument("--two-player", action="store_true",
                        help="drive a CONTESTED BLUE-dispatch + RED-block turn (a drawn terminal)")
    parser.add_argument("--scenario-dir", default=None)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    bytes_dir = REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid"
    if args.two_player:
        scn = Path(args.scenario_dir).resolve() if args.scenario_dir else SCENARIO_2P
        run_id = args.run_id or "contested-2p-001"
        byte_by_slot = {"BLUE": (bytes_dir / "dispatch_r1.json").read_bytes(),
                        "RED": (bytes_dir / "block_r1.json").read_bytes()}
    else:
        scn = Path(args.scenario_dir).resolve() if args.scenario_dir else SCENARIO
        run_id = args.run_id or "contested-agents-001"
        byte_by_slot = {"BLUE": (bytes_dir / "dispatch_r1.json").read_bytes()}
    driven = drive_turn(INITIAL_STATE, byte_by_slot, run_id=run_id, turn=0)
    commit_turn(scn, driven)
    rc = write_ledger_with_steps(scn, driven["llm_steps"])
    if rc != 0:
        return rc
    print(f"drove 1 turn into {scn.name}: {len(driven['llm_steps'])} llm_step(s), "
          f"{len(driven['artifacts'])} byte artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

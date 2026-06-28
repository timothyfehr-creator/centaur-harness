#!/usr/bin/env python3
"""The @live capture entrypoint (WP-A1b §1.2) — OUT of the green gate, human-run, spends real money.

It performs the ONE thing A1b adds over the offline substrate: call Opus (BLUE, then RED for a contested
turn), capture each REDACTED response + the canonical request envelope, and feed them through the IDENTICAL
offline pipeline (extract -> harness-bound identity -> assemble -> commit + LIVE llm_step). A live call is a
CAPTURE step, never a replay step: Opus has no seed and temperature is removed, so output is irreducibly
non-deterministic -- that is why record-and-replay is forced. Thereafter the committed (redacted) bytes are a
deterministic INPUT the offline gates validate; the model is NEVER re-called.

Refuses to run without BOTH --live and --i-am-spending-real-money, without ANTHROPIC_API_KEY, or with a
--raw-wire-dir inside the repo. Hard --max-calls cap. Proactive token spend guard BEFORE each call. A
served-model drift or a transport error is recorded EXCLUDED (run-local), never a committed binding step.

This module imports core.live_client (the network) and is therefore @live: allowlisted in
validate_no_network_imports, NEVER imported by a test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import agent_logistics as al  # noqa: E402
import live_client  # noqa: E402
import spend_guard as sg  # noqa: E402
import turn_record as tr  # noqa: E402
from agent_offline_run import FP, INITIAL_STATE, commit_turn, write_ledger_with_steps  # noqa: E402
from canon import CANON_VERSION, canonical_digest  # noqa: E402
from command_extractor import EXTRACTOR_VERSION, extract_command, project_semantic  # noqa: E402
from engine_projection import project_turn_record  # noqa: E402
from prompt_templates import (  # noqa: E402
    A1B_PROMPT_VERSION,
    canonical_request_bytes,
    render_request_envelope,
)
from response_redact import contains_prose, redact  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-opus-4-8"
ANTHROPIC_API_VERSION = "2023-06-01"
MODEL_ID_STABILITY = "PROVIDER_DOCUMENTED_PINNED_MODEL_ID_INFRA_MAY_CHANGE"
AUTHENTICITY = "RUNNER_ATTESTED_NOT_PROVEN"


def _decision_view(slot: str) -> dict:
    """The fog projection the player decides on: the PRE-turn state (turn-0 start), no events yet."""
    head = {"turn": 0, "resulting_state": INITIAL_STATE, "event_batch": []}
    return project_turn_record(slot, head)


def _live_step(slot: str, run_id: str, served_model: str, request_id: str, response: bytes, request: bytes,
               digest: str | None, reject_code: str | None) -> dict:
    """One LIVE llm_step (matches validate_agent_provenance's LIVE checks)."""
    return {
        "schema_version": "1.0", "run_id": run_id, "turn": 0, "recorded_turn": 0, "calling_slot": slot,
        "command_id": f"{run_id}:0:{slot}", "step_kind": "COMMAND" if reject_code is None else "FORFEIT",
        "capture_mode": "LIVE", "provider": "anthropic",
        "model": MODEL, "model_version": served_model, "served_model": served_model,
        "sampling": "PROVIDER_DEFAULT_NO_SEED", "prompt_version": A1B_PROMPT_VERSION,
        "extractor_version": EXTRACTOR_VERSION, "canon_version": CANON_VERSION,
        "response_sha256": hashlib.sha256(response).hexdigest(),
        "request_envelope_sha256": hashlib.sha256(request).hexdigest(),
        "extracted_command_digest": digest, "reject_code": reject_code, "as_of": "2026-06-28",
        "provider_request_id": request_id, "anthropic_api_version": ANTHROPIC_API_VERSION,
        "model_id_stability": MODEL_ID_STABILITY, "authenticity": AUTHENTICITY,
    }


def _fail(msg: str) -> int:
    print(f"REFUSED: {msg}", file=sys.stderr)
    return 2


def capture(slots: list[str], *, run_id: str, raw_wire_dir: Path, max_calls: int, token_cap: int,
            prompt_version: str) -> dict:
    """Make the live calls (bounded) and build {turn_record, llm_steps, artifacts, spend, excluded}."""
    commands: list = []
    steps: list = []
    artifacts: dict = {}
    spent_tokens = 0
    spend_micro = 0
    excluded: list = []
    calls = 0
    for slot in slots:
        view = _decision_view(slot)
        body = render_request_envelope(prompt_version, view)
        # canonical request bytes = OUR re-renderable serialization (the Tier-3 binding subject), float-free.
        request = canonical_request_bytes(prompt_version, view)
        # proactive spend guard (§4.1, §9: token-count fail-closed -> refuse, no estimate, no spend).
        try:
            in_tokens = live_client.count_input_tokens(body)
        except Exception as exc:  # noqa: BLE001 — any count_tokens failure means we cannot bound spend
            raise SystemExit(_fail(f"count_tokens failed for {slot} ({type(exc).__name__}: {exc}); no spend")) from exc
        ceiling = sg.call_ceiling_tokens(in_tokens, body["max_tokens"])
        if calls >= max_calls:
            raise SystemExit(_fail(f"--max-calls {max_calls} reached before {slot}"))
        if not sg.affordable(spent_tokens, ceiling, token_cap):
            raise SystemExit(_fail(f"spend guard: {slot} ceiling {ceiling} + spent {spent_tokens} > cap {token_cap}"))
        print(f"  [{slot}] calling {MODEL} (input ~{in_tokens} tok, ceiling {ceiling} tok)…", file=sys.stderr)
        result = live_client.call(body)
        calls += 1
        spent_tokens += result.input_tokens + result.output_tokens
        spend_micro += sg.micro_usd(result.input_tokens, result.output_tokens)
        # served-model drift -> EXCLUDED (no usable binding; retain run-local, never a committed step).
        if result.served_model != MODEL:
            (raw_wire_dir / f"{slot}.EXCLUDED.drift.json").write_bytes(result.wire_response_bytes)
            excluded.append({"slot": slot, "reason": "served-model-drift", "served": result.served_model})
            print(f"  [{slot}] EXCLUDED: served model {result.served_model!r} != {MODEL!r}", file=sys.stderr)
            continue
        if not result.provider_request_id:
            (raw_wire_dir / f"{slot}.EXCLUDED.noreqid.json").write_bytes(result.wire_response_bytes)
            excluded.append({"slot": slot, "reason": "missing-request-id"})
            print(f"  [{slot}] EXCLUDED: no provider request-id", file=sys.stderr)
            continue
        # keep the FULL wire bytes run-local (operator authenticity glance); they carry prose.
        (raw_wire_dir / f"{slot}.wire.json").write_bytes(result.wire_response_bytes)
        response = redact(result.wire_response_bytes)        # prose-stripped committed body (§1.4)
        assert contains_prose(response) == [], f"redaction left prose for {slot}"   # belt: never commit prose
        artifacts[hashlib.sha256(response).hexdigest()] = response
        artifacts[hashlib.sha256(request).hexdigest()] = request
        res = extract_command(response)
        if res.ok:
            commands.append({"command_id": f"{run_id}:0:{slot}", "turn": 0, "actor_id": slot,
                             "action_type": res.command["action_type"], "params": res.command["params"]})
            digest = canonical_digest(project_semantic(res.command))["value"]
            steps.append(_live_step(slot, run_id, result.served_model, result.provider_request_id,
                                    response, request, digest, None))
        else:  # a 200 OK that is not exactly one well-formed command -> recorded FORFEIT (NO_OP), bytes committed.
            steps.append(_live_step(slot, run_id, result.served_model, result.provider_request_id,
                                    response, request, None, res.reject_code))
            print(f"  [{slot}] FORFEIT: {res.reject_code}", file=sys.stderr)
    out = tr.assemble(turn=0, start_state=INITIAL_STATE, commands=commands, master_seed=0,
                      runtime_fingerprint=FP, successor_slot="run/turns/0001.json", resolver=al)
    if out["status"] != "resolved":
        raise SystemExit(_fail(f"turn rejected by the engine: {out.get('rejections')}"))
    return {"turn_record": out["turn_record"], "llm_steps": steps, "artifacts": artifacts,
            "spend_micro": spend_micro, "spent_tokens": spent_tokens, "excluded": excluded}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent_live_capture.py", description="Capture ONE live contested turn (@live).")
    p.add_argument("--scenario-dir", required=True, help="the committed CAPTURE_ARTIFACT scenario shell")
    p.add_argument("--raw-wire-dir", required=True, help="where the FULL wire bytes go — MUST be OUTSIDE the repo")
    p.add_argument("--run-id", default="contested-live-001")
    p.add_argument("--two-player", action="store_true", help="capture BLUE + RED (a contested turn)")
    p.add_argument("--max-calls", type=int, default=2)
    p.add_argument("--token-cap", type=int, default=sg.DEFAULT_TOKEN_CAP)
    p.add_argument("--prompt-version", default=A1B_PROMPT_VERSION)
    p.add_argument("--live", action="store_true", help="required: confirm this makes a real network call")
    p.add_argument("--i-am-spending-real-money", action="store_true", help="required: confirm real spend")
    args = p.parse_args(argv)

    # --- refuse-to-run guards (no spend reachable until all pass) ---
    if not (args.live and args.i_am_spending_real_money):
        return _fail("both --live and --i-am-spending-real-money are required")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _fail("ANTHROPIC_API_KEY is not set in the environment")
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return _fail("both ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are set (ambiguous credential)")
    if max(args.max_calls, 0) > 2:
        return _fail("--max-calls may not exceed 2 (A1b single-turn cap)")
    raw_wire_dir = Path(args.raw_wire_dir).expanduser().resolve()
    try:
        raw_wire_dir.relative_to(REPO_ROOT)
        return _fail(f"--raw-wire-dir {raw_wire_dir} is INSIDE the repo (the full wire bytes carry prose)")
    except ValueError:
        pass  # good: outside the repo
    raw_wire_dir.mkdir(parents=True, exist_ok=True)
    key = os.environ["ANTHROPIC_API_KEY"]
    print(f"credential: ANTHROPIC_API_KEY present (…{key[-4:]}); raw-wire -> {raw_wire_dir}", file=sys.stderr)

    slots = ["BLUE", "RED"] if args.two_player else ["BLUE"]
    driven = capture(slots, run_id=args.run_id, raw_wire_dir=raw_wire_dir, max_calls=args.max_calls,
                     token_cap=args.token_cap, prompt_version=args.prompt_version)
    scn = Path(args.scenario_dir).resolve()
    commit_turn(scn, driven)
    rc = write_ledger_with_steps(scn, driven["llm_steps"])
    if rc != 0:
        return rc
    # advisory spend ledger -> run-local (gitignored).
    (scn / "run" / "llm_spend.local.json").write_text(json.dumps({
        "spent_tokens": driven["spent_tokens"], "spend_estimate": sg.format_usd(driven["spend_micro"]),
        "excluded": driven["excluded"], "price_source": sg.PRICE_SOURCE, "price_as_of": sg.PRICE_AS_OF,
    }, indent=2), encoding="utf-8")
    print(f"captured {len([s for s in driven['llm_steps']])} live step(s) into {scn.name}; "
          f"spend ~{sg.format_usd(driven['spend_micro'])} ({driven['spent_tokens']} tok); "
          f"excluded={driven['excluded']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""The @live capture entrypoint (WP-A1b §1.2) — OUT of the green gate, human-run, spends real money.

It performs the ONE thing A1b adds over the offline substrate: call Opus (BLUE, then RED for a contested
turn), capture each REDACTED response + the canonical request envelope, and feed them through the IDENTICAL
offline pipeline (extract -> harness-bound identity -> assemble -> commit + LIVE llm_step). A live call is a
CAPTURE step, never a replay step: Opus has no seed and temperature is removed, so output is irreducibly
non-deterministic -- that is why record-and-replay is forced. Thereafter the committed (redacted) bytes are a
deterministic INPUT the offline gates validate; the model is NEVER re-called.

Refuses to run without BOTH --live and --i-am-spending-real-money, without ANTHROPIC_API_KEY, or with a
--raw-wire-dir inside the repo. A bad/illegal order is re-asked with its public reject code up to
--max-retries times before forfeiting (WP-A2); the worst-case call count (slots x (1+retries)) bounds it, plus
a proactive token spend guard BEFORE each call. A served-model drift or a transport error is recorded EXCLUDED
(run-local), never a committed binding step. The retry loop (run_slot_attempts) is the SAME one the offline
tests exercise; the live `fetch` is the only network seam.

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
from agent_offline_run import (  # noqa: E402
    FP,
    INITIAL_STATE,
    _prior_attempt,
    commit_turn,
    run_slot_attempts,
    write_ledger_with_steps,
)
from canon import CANON_VERSION  # noqa: E402
from command_extractor import EXTRACTOR_VERSION  # noqa: E402
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


def _live_step(slot: str, run_id: str, served_model: str, request_id: str, response: bytes, request: bytes,
               digest: str | None, reject_code: str | None, turn: int = 0, prompt_version: str = A1B_PROMPT_VERSION,
               *, correction: str | None = None, prior_attempts: list | None = None) -> dict:
    """One LIVE llm_step (matches validate_agent_provenance's LIVE checks). turn defaults to 0 for the
    single-turn capture; the multi-turn campaign passes the actual turn (shared step builder, one source).
    correction / prior_attempts (WP-A2 retry) are OMITTED when absent, so a no-retry step is byte-identical
    to the pre-retry producer."""
    step = {
        "schema_version": "1.0", "run_id": run_id, "turn": turn, "recorded_turn": turn, "calling_slot": slot,
        "command_id": f"{run_id}:{turn}:{slot}",
        "step_kind": ("COMMAND" if digest is not None and reject_code is None
                      else "ILLEGAL_FORFEIT" if digest is not None else "FORFEIT"),
        "capture_mode": "LIVE", "provider": "anthropic",
        "model": MODEL, "model_version": served_model, "served_model": served_model,
        "sampling": "PROVIDER_DEFAULT_NO_SEED", "prompt_version": prompt_version,
        "extractor_version": EXTRACTOR_VERSION, "canon_version": CANON_VERSION,
        "response_sha256": hashlib.sha256(response).hexdigest(),
        "request_envelope_sha256": hashlib.sha256(request).hexdigest(),
        "extracted_command_digest": digest, "reject_code": reject_code, "as_of": "2026-06-28",
        "provider_request_id": request_id, "anthropic_api_version": ANTHROPIC_API_VERSION,
        "model_id_stability": MODEL_ID_STABILITY, "authenticity": AUTHENTICITY,
    }
    if correction is not None:
        step["correction"] = correction
    if prior_attempts:
        step["prior_attempts"] = prior_attempts
    return step


def live_drive_slot(slot: str, head: dict, turn: int, *, run_id: str, raw_wire_dir: Path, prompt_version: str,
                    max_retries: int, spend_ok, on_spent) -> dict:
    """Run the live retry loop for ONE (turn, slot): render the slot's fog of the CURRENT head, call Opus up
    to 1+max_retries times (correcting on each model REJECT), classify via the SAME run_slot_attempts loop the
    offline tests exercise. ``spend_ok(in_tokens, max_tokens) -> bool`` is the PROACTIVE per-attempt gate
    (checked BEFORE each call); ``on_spent(in_tokens, out_tokens)`` accumulates after each call. Returns
    {command, step, artifacts, excluded, refused}: the DECISIVE attempt binds a LIVE step carrying its
    correction + the gate-verified prior_attempts; rejected priors keep their committed bytes; EXCLUDED
    (served-model drift / no request-id) and transport refusals never become a committed step."""
    view = project_turn_record(slot, {"turn": turn, "resulting_state": head, "event_batch": []})
    artifacts: dict = {}
    excluded: list = []
    meta: dict = {}                                   # response_sha -> (served_model, request_id) for the step
    flags = {"refused_before_any": False}

    def fetch(idx: int, correction: str | None):
        body = render_request_envelope(prompt_version, view, correction)
        request = canonical_request_bytes(prompt_version, view, correction)
        try:
            in_tokens = live_client.count_input_tokens(body)
        except Exception as exc:  # noqa: BLE001 — a count_tokens failure means we cannot bound spend -> refuse
            raise SystemExit(_fail(f"count_tokens failed (turn {turn} {slot}: {type(exc).__name__}); no spend")) from exc
        if not spend_ok(in_tokens, body["max_tokens"]):
            flags["refused_before_any"] = (idx == 0)   # cap hit before ANY attempt -> the whole slot is refused
            return None
        tag = f"{turn:04d}.{slot}" + (f".retry{idx}" if idx else "")
        result = live_client.call(body)
        on_spent(result.input_tokens, result.output_tokens)
        if result.served_model != MODEL:               # capture-integrity failure -> EXCLUDED (run-local)
            (raw_wire_dir / f"{tag}.EXCLUDED.drift.json").write_bytes(result.wire_response_bytes)
            excluded.append({"turn": turn, "slot": slot, "reason": "served-model-drift", "served": result.served_model})
            return None
        if not result.provider_request_id:
            (raw_wire_dir / f"{tag}.EXCLUDED.noreqid.json").write_bytes(result.wire_response_bytes)
            excluded.append({"turn": turn, "slot": slot, "reason": "missing-request-id"})
            return None
        (raw_wire_dir / f"{tag}.wire.json").write_bytes(result.wire_response_bytes)   # prose stays run-local
        response = redact(result.wire_response_bytes)
        assert contains_prose(response) == [], f"redaction left prose for {slot} turn {turn} attempt {idx}"
        meta[hashlib.sha256(response).hexdigest()] = (result.served_model, result.provider_request_id)
        return (response, request)

    res = run_slot_attempts(slot, turn, run_id, head, fetch, max_retries)
    if res is None:                                    # no committed attempt (spend cap or all EXCLUDED)
        return {"command": None, "step": None, "artifacts": artifacts, "excluded": excluded,
                "refused": flags["refused_before_any"]}
    dec, priors = res["decisive"], res["priors"]
    for a in (dec, *priors):
        artifacts[hashlib.sha256(a["response"]).hexdigest()] = a["response"]
        artifacts[hashlib.sha256(a["request"]).hexdigest()] = a["request"]
    sm, rid = meta[hashlib.sha256(dec["response"]).hexdigest()]
    step = _live_step(slot, run_id, sm, rid, dec["response"], dec["request"], dec["digest"], dec["reject"],
                      turn=turn, prompt_version=prompt_version, correction=dec["correction"],
                      prior_attempts=[_prior_attempt(a) for a in priors])
    return {"command": dec["command"], "step": step, "artifacts": artifacts, "excluded": excluded, "refused": False}


def _fail(msg: str) -> int:
    print(f"REFUSED: {msg}", file=sys.stderr)
    return 2


def capture(slots: list[str], *, run_id: str, raw_wire_dir: Path, max_calls: int, token_cap: int,
            prompt_version: str, max_retries: int = 0) -> dict:
    """Make the live calls (bounded, retry-capable) and build {turn_record, llm_steps, artifacts, spend,
    excluded}. Spend is a per-attempt call-count + token cap (the proactive guard, fail-closed on count)."""
    commands: list = []
    steps: list = []
    artifacts: dict = {}
    excluded: list = []
    spend = {"tokens": 0, "micro": 0, "calls": 0}

    def spend_ok(in_tokens: int, max_tokens: int) -> bool:
        if spend["calls"] >= max_calls:
            return False
        return sg.affordable(spend["tokens"], sg.call_ceiling_tokens(in_tokens, max_tokens), token_cap)

    def on_spent(in_t: int, out_t: int) -> None:
        spend["calls"] += 1
        spend["tokens"] += in_t + out_t
        spend["micro"] += sg.micro_usd(in_t, out_t)

    for slot in slots:
        r = live_drive_slot(slot, INITIAL_STATE, 0, run_id=run_id, raw_wire_dir=raw_wire_dir,
                            prompt_version=prompt_version, max_retries=max_retries, spend_ok=spend_ok, on_spent=on_spent)
        artifacts.update(r["artifacts"])
        excluded.extend(r["excluded"])
        if r["refused"]:
            raise SystemExit(_fail(f"spend/call cap reached before {slot} (calls {spend['calls']}/{max_calls})"))
        if r["step"] is None:                              # all attempts EXCLUDED -> no committed step this slot
            continue
        steps.append(r["step"])
        if r["command"]:
            commands.append(r["command"])
        else:
            print(f"  [{slot}] {r['step']['step_kind']} {r['step'].get('reject_code')}", file=sys.stderr)
    out = tr.assemble(turn=0, start_state=INITIAL_STATE, commands=commands, master_seed=0,
                      runtime_fingerprint=FP, successor_slot="run/turns/0001.json", resolver=al)
    if out["status"] != "resolved":
        raise SystemExit(_fail(f"turn rejected by the engine: {out.get('rejections')}"))
    return {"turn_record": out["turn_record"], "llm_steps": steps, "artifacts": artifacts,
            "spend_micro": spend["micro"], "spent_tokens": spend["tokens"], "excluded": excluded}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent_live_capture.py", description="Capture ONE live contested turn (@live).")
    p.add_argument("--scenario-dir", required=True, help="the committed CAPTURE_ARTIFACT scenario shell")
    p.add_argument("--raw-wire-dir", required=True, help="where the FULL wire bytes go — MUST be OUTSIDE the repo")
    p.add_argument("--run-id", default="contested-live-001")
    p.add_argument("--two-player", action="store_true", help="capture BLUE + RED (a contested turn)")
    p.add_argument("--max-retries", type=int, default=2,
                   help="corrected retries per (turn,slot) before forfeit (WP-A2; 0 = the old one-shot capture)")
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
    if args.max_retries not in range(0, 5):
        return _fail("--max-retries must be 0..4")
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
    max_calls = len(slots) * (1 + args.max_retries)   # worst-case calls for ONE turn (all slots exhaust retries)
    driven = capture(slots, run_id=args.run_id, raw_wire_dir=raw_wire_dir, max_calls=max_calls,
                     token_cap=args.token_cap, prompt_version=args.prompt_version, max_retries=args.max_retries)
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

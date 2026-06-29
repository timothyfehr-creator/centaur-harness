#!/usr/bin/env python3
"""Multi-turn / two-player live game capture (WP-A3) — @live, OUT of the green gate, spends real money.

Opus plays BOTH sides over several turns; the deterministic engine referees each turn; the state advances via
the BYTE-IDENTICAL head handoff (turn N's resulting_state == turn N+1's start_state, exactly as the offline
campaign). The whole game is ONE `CAPTURE_ARTIFACT` (n=1), committed as a chain, and replays with the model
never re-called.

HONESTY: each player is a MEMORYLESS one-shot reasoner per turn — called fresh on the current-turn fog
projection, with no conversation history and no memory of its own prior moves (weaker than a remembering
commander; must not be presented as a continuous strategist). A single game is NEVER a sample; it is one
machine log, never aggregated into a frequency/probability.

This module imports core.live_client (the network) so it is @live: allowlisted in validate_no_network_imports,
NEVER imported by a test. The honesty-critical pieces (redact, extract, the closed legality screen, the LIVE
step builder, the spend guard) are the SAME shared functions the single-turn capture uses.

Refuses without BOTH --live and --i-am-spending-real-money, without ANTHROPIC_API_KEY, with both creds set, or
with a --raw-wire-dir inside the repo. A proactive per-game $ spend cap is checked BEFORE each call; an
illegal move forfeits that slot (WP-A2a), so an illegal move never crashes the game.
"""
from __future__ import annotations

import argparse
import copy
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
from agent_live_capture import (  # noqa: E402 — shared constants + the LIVE step builder
    MODEL,
    _fail,
    _live_step,
)
from agent_offline_run import FP, INITIAL_STATE, both_blockable_state, write_ledger_with_steps  # noqa: E402
from canon import canonical_digest  # noqa: E402
from command_extractor import extract_command, project_semantic  # noqa: E402
from engine_projection import project_turn_record  # noqa: E402
from prompt_templates import (  # noqa: E402
    A1B_PROMPT_VERSION,
    canonical_request_bytes,
    render_request_envelope,
)
from response_redact import contains_prose, redact  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _start_state(*, origin: int, threshold: int, r2_threshold: int | None = None) -> dict:
    """INITIAL_STATE with the curated-condition overrides (BLUE's starting supply + the hidden block
    threshold). With r2_threshold set, BOTH roads are blockable (the 'RED matters' game) -- reusing the same
    agent_offline_run.both_blockable_state builder the offline coverage exercises, so the topology cannot drift."""
    if r2_threshold is not None:
        return both_blockable_state(origin=origin, r1_threshold=threshold, r2_threshold=r2_threshold)
    s = copy.deepcopy(INITIAL_STATE)
    s["state"]["entities"][0]["fields"]["origin"]["value"] = origin            # blue_supply.origin
    s["state"]["entities"][3]["fields"]["block_threshold"]["value"] = threshold  # route_secret:r1 (adjudicator-only)
    return s


def _capture_call(slot: str, head: dict, turn: int, *, run_id: str, raw_wire_dir: Path, prompt_version: str,
                  spent_micro: int, max_spend_micro: int) -> dict:
    """Render the slot's fog view of the CURRENT head, proactively spend-guard, call Opus once, redact +
    classify. Returns {refused} OR {command|None, step, artifacts, in_tokens, out_tokens, excluded|None}."""
    view = project_turn_record(slot, {"turn": turn, "resulting_state": head, "event_batch": []})
    body = render_request_envelope(prompt_version, view)
    request = canonical_request_bytes(prompt_version, view)
    try:
        in_est = live_client.count_input_tokens(body)
    except Exception as exc:  # noqa: BLE001 — a count_tokens failure means we cannot bound spend -> refuse
        raise SystemExit(_fail(f"count_tokens failed (turn {turn} {slot}: {type(exc).__name__}); no spend")) from exc
    if spent_micro + sg.micro_usd(in_est, body["max_tokens"]) > max_spend_micro:
        return {"refused": True}
    result = live_client.call(body)
    out: dict = {"refused": False, "command": None, "step": None, "artifacts": {},
                 "in_tokens": result.input_tokens, "out_tokens": result.output_tokens, "excluded": None}
    if result.served_model != MODEL:                       # capture-integrity failure -> EXCLUDED (run-local)
        (raw_wire_dir / f"{turn:04d}.{slot}.EXCLUDED.drift.json").write_bytes(result.wire_response_bytes)
        out["excluded"] = {"turn": turn, "slot": slot, "reason": "served-model-drift", "served": result.served_model}
        return out
    if not result.provider_request_id:
        (raw_wire_dir / f"{turn:04d}.{slot}.EXCLUDED.noreqid.json").write_bytes(result.wire_response_bytes)
        out["excluded"] = {"turn": turn, "slot": slot, "reason": "missing-request-id"}
        return out
    (raw_wire_dir / f"{turn:04d}.{slot}.wire.json").write_bytes(result.wire_response_bytes)   # prose stays run-local
    response = redact(result.wire_response_bytes)
    assert contains_prose(response) == [], f"redaction left prose for {slot} turn {turn}"
    out["artifacts"][hashlib.sha256(response).hexdigest()] = response
    out["artifacts"][hashlib.sha256(request).hexdigest()] = request
    res = extract_command(response)
    sm, rid = result.served_model, result.provider_request_id
    if res.ok:
        cmd = {"command_id": f"{run_id}:{turn}:{slot}", "turn": turn, "actor_id": slot,
               "action_type": res.command["action_type"], "params": res.command["params"]}
        digest = canonical_digest(project_semantic(res.command))["value"]
        legality = al.command_legality(cmd, head)          # the engine's verdict on the harness-bound command
        if legality is None:
            out["command"] = cmd
            out["step"] = _live_step(slot, run_id, sm, rid, response, request, digest, None, turn=turn)
        else:                                              # well-formed but illegal -> forfeit (NO crash)
            out["step"] = _live_step(slot, run_id, sm, rid, response, request, digest, legality, turn=turn)
    else:                                                  # not well-formed -> FORFEIT
        out["step"] = _live_step(slot, run_id, sm, rid, response, request, None, res.reject_code, turn=turn)
    return out


def run_game(slots: list[str], *, run_id: str, raw_wire_dir: Path, turns: int, start_state: dict,
             prompt_version: str, max_spend_micro: int) -> dict:
    """Drive a multi-turn game off the byte-identical head handoff. A spend-cap or an exhausted game stops it
    early (a committed prefix is a legal chain). Returns {records, llm_steps, artifacts, spend, excluded, stop}."""
    head = start_state
    records: list = []
    steps: list = []
    artifacts: dict = {}
    excluded: list = []
    spent_tokens = 0
    spend_micro = 0
    stop = "horizon"
    for turn in range(turns):
        commands: list = []
        for slot in slots:
            r = _capture_call(slot, head, turn, run_id=run_id, raw_wire_dir=raw_wire_dir,
                              prompt_version=prompt_version, spent_micro=spend_micro, max_spend_micro=max_spend_micro)
            if r.get("refused"):
                print(f"  spend cap {sg.format_usd(max_spend_micro)} reached at turn {turn} {slot}; stopping",
                      file=sys.stderr)
                stop = "spend-cap"
                return _bundle(records, steps, artifacts, spent_tokens, spend_micro, excluded, stop)
            spent_tokens += r["in_tokens"] + r["out_tokens"]
            spend_micro += sg.micro_usd(r["in_tokens"], r["out_tokens"])
            artifacts.update(r["artifacts"])
            if r["excluded"]:
                excluded.append(r["excluded"])
                print(f"  [turn {turn} {slot}] EXCLUDED {r['excluded']['reason']}", file=sys.stderr)
                continue
            steps.append(r["step"])
            if r["command"]:
                commands.append(r["command"])
            else:
                print(f"  [turn {turn} {slot}] {r['step']['step_kind']} {r['step'].get('reject_code')}", file=sys.stderr)
        out = tr.assemble(turn=turn, start_state=head, commands=commands, master_seed=0, runtime_fingerprint=FP,
                          successor_slot=f"run/turns/{turn + 1:04d}.json", resolver=al)
        if out["status"] != "resolved":                    # backstop: illegal moves were pre-screened to forfeits
            raise SystemExit(_fail(f"turn {turn} rejected by the engine: {out.get('rejections')}"))
        records.append(out["turn_record"])
        head = out["turn_record"]["resulting_state"]       # BYTE-IDENTICAL handoff
    return _bundle(records, steps, artifacts, spent_tokens, spend_micro, excluded, stop)


def _bundle(records, steps, artifacts, spent_tokens, spend_micro, excluded, stop) -> dict:
    return {"records": records, "llm_steps": steps, "artifacts": artifacts, "spent_tokens": spent_tokens,
            "spend_micro": spend_micro, "excluded": excluded, "stop": stop}


def _commit_game(scn: Path, game: dict) -> None:
    """Write the turn-record chain + the content-addressed bytes + the ledger with all llm_steps."""
    (scn / "run" / "turns").mkdir(parents=True, exist_ok=True)
    (scn / "run" / "llm").mkdir(parents=True, exist_ok=True)
    for rec in game["records"]:
        tr.commit(rec, str(scn / "run" / "turns" / f"{rec['turn']:04d}.json"))
    for sha, raw in game["artifacts"].items():
        (scn / "run" / "llm" / f"{sha}.json").write_bytes(raw)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agent_live_campaign.py", description="Capture ONE multi-turn live game (@live).")
    p.add_argument("--scenario-dir", required=True)
    p.add_argument("--raw-wire-dir", required=True, help="full wire bytes go here — MUST be OUTSIDE the repo")
    p.add_argument("--run-id", default="live-game-001")
    p.add_argument("--two-player", action="store_true", help="BLUE + RED each turn (else BLUE only)")
    p.add_argument("--turns", type=int, default=5)
    p.add_argument("--start-origin", type=int, default=100, help="BLUE starting supply (a curated condition)")
    p.add_argument("--threshold", type=int, default=73, help="hidden r1 block threshold; block succeeds iff d100 < it")
    p.add_argument("--r2-threshold", type=int, default=None,
                   help="hidden r2 block threshold; if set, BOTH roads are blockable (the 'RED matters' game)")
    p.add_argument("--max-spend-usd", type=float, default=2.0, help="per-game proactive $ cap")
    p.add_argument("--prompt-version", default=A1B_PROMPT_VERSION)
    p.add_argument("--live", action="store_true")
    p.add_argument("--i-am-spending-real-money", action="store_true")
    args = p.parse_args(argv)

    if not (args.live and args.i_am_spending_real_money):
        return _fail("both --live and --i-am-spending-real-money are required")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _fail("ANTHROPIC_API_KEY is not set")
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return _fail("both ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are set (ambiguous credential)")
    if args.turns < 1 or args.turns > 12:
        return _fail("--turns must be in [1,12]")
    raw_wire_dir = Path(args.raw_wire_dir).expanduser().resolve()
    try:
        raw_wire_dir.relative_to(REPO_ROOT)
        return _fail(f"--raw-wire-dir {raw_wire_dir} is INSIDE the repo (the full wire bytes carry prose)")
    except ValueError:
        pass
    raw_wire_dir.mkdir(parents=True, exist_ok=True)
    key = os.environ["ANTHROPIC_API_KEY"]
    print(f"credential: ANTHROPIC_API_KEY (…{key[-4:]}); raw-wire -> {raw_wire_dir}; "
          f"origin={args.start_origin} threshold={args.threshold} turns={args.turns} "
          f"two_player={args.two_player} cap={args.max_spend_usd}", file=sys.stderr)

    slots = ["BLUE", "RED"] if args.two_player else ["BLUE"]
    start = _start_state(origin=args.start_origin, threshold=args.threshold, r2_threshold=args.r2_threshold)
    game = run_game(slots, run_id=args.run_id, raw_wire_dir=raw_wire_dir, turns=args.turns, start_state=start,
                    prompt_version=args.prompt_version, max_spend_micro=int(round(args.max_spend_usd * 1_000_000)))
    scn = Path(args.scenario_dir).resolve()
    _commit_game(scn, game)
    rc = write_ledger_with_steps(scn, game["llm_steps"])
    if rc != 0:
        return rc
    (scn / "run" / "llm_spend.local.json").write_text(json.dumps({
        "spent_tokens": game["spent_tokens"], "spend_estimate": sg.format_usd(game["spend_micro"]),
        "turns_committed": len(game["records"]), "stop": game["stop"], "excluded": game["excluded"],
        "price_source": sg.PRICE_SOURCE, "price_as_of": sg.PRICE_AS_OF}, indent=2), encoding="utf-8")
    print(f"captured {len(game['records'])} turn(s) into {scn.name}: {len(game['llm_steps'])} live step(s); "
          f"spend ~{sg.format_usd(game['spend_micro'])} ({game['spent_tokens']} tok); stop={game['stop']}; "
          f"excluded={game['excluded']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

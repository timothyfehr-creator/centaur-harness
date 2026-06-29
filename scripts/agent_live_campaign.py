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
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import agent_logistics as al  # noqa: E402
import spend_guard as sg  # noqa: E402
import turn_record as tr  # noqa: E402
from agent_live_capture import (  # noqa: E402 — the SHARED live per-slot drive (one source, cannot drift)
    _fail,
    live_drive_slot,
)
from agent_offline_run import FP, INITIAL_STATE, both_blockable_state, write_ledger_with_steps  # noqa: E402
from prompt_templates import (  # noqa: E402
    A1B_PROMPT_VERSION,
)

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


def run_game(slots: list[str], *, run_id: str, raw_wire_dir: Path, turns: int, start_state: dict,
             prompt_version: str, max_spend_micro: int, max_retries: int = 0) -> dict:
    """Drive a multi-turn game off the byte-identical head handoff. Each (turn, slot) goes through the SHARED
    live_drive_slot retry loop (correcting on each model reject, up to max_retries). A per-game $ cap or an
    exhausted game stops it early (a committed prefix is a legal chain). Returns {records, llm_steps,
    artifacts, spend, excluded, stop}."""
    head = start_state
    records: list = []
    steps: list = []
    artifacts: dict = {}
    excluded: list = []
    spend = {"tokens": 0, "micro": 0}
    stop = "horizon"

    def spend_ok(in_tokens: int, max_tokens: int) -> bool:   # proactive per-attempt $ cap (cumulative game spend)
        return spend["micro"] + sg.micro_usd(in_tokens, max_tokens) <= max_spend_micro

    def on_spent(in_t: int, out_t: int) -> None:
        spend["tokens"] += in_t + out_t
        spend["micro"] += sg.micro_usd(in_t, out_t)

    for turn in range(turns):
        commands: list = []
        for slot in slots:
            r = live_drive_slot(slot, head, turn, run_id=run_id, raw_wire_dir=raw_wire_dir,
                                prompt_version=prompt_version, max_retries=max_retries,
                                spend_ok=spend_ok, on_spent=on_spent)
            artifacts.update(r["artifacts"])
            for ex in r["excluded"]:
                excluded.append(ex)
                print(f"  [turn {turn} {slot}] EXCLUDED {ex['reason']}", file=sys.stderr)
            if r["refused"]:
                print(f"  spend cap {sg.format_usd(max_spend_micro)} reached at turn {turn} {slot}; stopping",
                      file=sys.stderr)
                stop = "spend-cap"
                return _bundle(records, steps, artifacts, spend["tokens"], spend["micro"], excluded, stop)
            if r["step"] is None:                            # all attempts EXCLUDED -> no committed step this slot
                continue
            steps.append(r["step"])
            if r["command"]:
                commands.append(r["command"])
            else:
                print(f"  [turn {turn} {slot}] {r['step']['step_kind']} {r['step'].get('reject_code')}"
                      f"{' (retried)' if r['step'].get('prior_attempts') else ''}", file=sys.stderr)
        out = tr.assemble(turn=turn, start_state=head, commands=commands, master_seed=0, runtime_fingerprint=FP,
                          successor_slot=f"run/turns/{turn + 1:04d}.json", resolver=al)
        if out["status"] != "resolved":                    # backstop: illegal moves were pre-screened to forfeits
            raise SystemExit(_fail(f"turn {turn} rejected by the engine: {out.get('rejections')}"))
        records.append(out["turn_record"])
        head = out["turn_record"]["resulting_state"]       # BYTE-IDENTICAL handoff
    return _bundle(records, steps, artifacts, spend["tokens"], spend["micro"], excluded, stop)


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
    p.add_argument("--max-retries", type=int, default=2,
                   help="corrected retries per (turn,slot) before forfeit (WP-A2; 0 = no retry)")
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
    if args.max_retries not in range(0, 5):
        return _fail("--max-retries must be 0..4")
    game = run_game(slots, run_id=args.run_id, raw_wire_dir=raw_wire_dir, turns=args.turns, start_state=start,
                    prompt_version=args.prompt_version, max_spend_micro=int(round(args.max_spend_usd * 1_000_000)),
                    max_retries=args.max_retries)
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

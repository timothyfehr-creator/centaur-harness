#!/usr/bin/env python3
"""Offline agent campaign (WP-A1a) — chain multi-turn agent turns, zero network.

A campaign is `agent_offline_run.drive_turn` iterated: each turn is driven from its own hand-authored
response bytes, and turn N's SEALED resulting_state becomes turn N+1's start_state byte-identically (the
head handoff). The committed chain (run/turns/0000.json, 0001.json, ...) passes
`validate_turn_replay.check_chain` (ordered, gap-free, byte-identical handoff, monotone as_of_turn, one
resolver) and binds per-turn under `validate_agent_provenance`.

Run as a script, it (re)generates examples/contested_logistics_campaign/ (a 3-turn BLUE-dispatch chain).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import agent_offline_run as drive  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CAMPAIGN = REPO_ROOT / "examples" / "contested_logistics_campaign"


def run_campaign(start_state: dict, per_turn_bytes: list[dict], *, run_id: str) -> list[dict]:
    """Drive a chain of turns. PURE (no I/O). turn N's SEALED resulting_state is turn N+1's start_state."""
    drivens: list[dict] = []
    head = start_state
    for turn, byte_by_slot in enumerate(per_turn_bytes):
        driven = drive.drive_turn(head, byte_by_slot, run_id=run_id, turn=turn)
        drivens.append(driven)
        head = driven["turn_record"]["resulting_state"]   # sealed envelope -> next start (byte-identical)
    return drivens


def commit_campaign(scenario_dir: Path, drivens: list[dict]) -> int:
    """Commit every turn's record + content-addressed bytes, then write the run-ledger with ALL llm_steps."""
    all_steps: list = []
    for driven in drivens:
        drive.commit_turn(scenario_dir, driven)
        all_steps.extend(driven["llm_steps"])
    return drive.write_ledger_with_steps(scenario_dir, all_steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_offline_campaign.py",
                                     description="(Re)generate the offline agent campaign (a multi-turn chain).")
    parser.add_argument("--scenario-dir", default=str(CAMPAIGN))
    parser.add_argument("--run-id", default="contested-campaign-001")
    parser.add_argument("--turns", type=int, default=3)
    args = parser.parse_args(argv)
    scn = Path(args.scenario_dir).resolve()
    dispatch = (REPO_ROOT / "tests" / "fixtures" / "agent_bytes" / "valid" / "dispatch_r1.json").read_bytes()
    per_turn_bytes = [{"BLUE": dispatch} for _ in range(args.turns)]   # BLUE dispatches 30 on r1 each turn
    drivens = run_campaign(drive.INITIAL_STATE, per_turn_bytes, run_id=args.run_id)
    rc = commit_campaign(scn, drivens)
    if rc != 0:
        return rc
    print(f"drove {len(drivens)} turns into {scn.name}: "
          f"{sum(len(d['llm_steps']) for d in drivens)} llm_step(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

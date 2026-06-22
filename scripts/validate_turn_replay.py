"""Turn-replay gate (WP-E1) — record-replay + recomputation over committed turn records.

Globs ``examples/**/run/turns/*.json``. For each committed turn record:
  - record-replay: ``reduce(start_state, event_batch)`` reproduces the committed resulting state
    (matched on the ``state_digest`` over the state field).
  - recomputation: re-running the resolver from ``start_state`` + ``command_batch`` + the recorded
    seed reproduces the same ``event_batch`` and resulting state, byte-identically.
  - structural: ``rng`` is null iff no draw was consumed; every stochastic terminal references a draw.

Exit codes: 0 = all verified, 1 = finding(s), 2 = usage / fail-closed (no records found / unreadable).
Findings to stderr as ``  - {code}  {where}  {msg}``. Matches the validator convention.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import canon  # noqa: E402
import resolver as rsv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
_TERMINALS = ("SUPPLY_DELIVERED", "SUPPLY_LOST")


def check_record(rec: dict, where: str) -> list:
    problems: list = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    has_draws = bool(rec.get("draw_records"))
    if has_draws and rec.get("rng") is None:
        add("rng-missing", "draw_records present but rng block is null")
    if not has_draws and rec.get("rng") is not None:
        add("decorative-seed", "rng block present but no draw was consumed")

    # record-replay
    try:
        rederived = rsv.reduce(rec["start_state"], rec["event_batch"])
    except Exception as exc:  # noqa: BLE001
        add("reduce-failed", f"reduce raised: {exc}")
        return problems
    if canon.canonical_digest(rederived["state"]) != rec["resulting_state"]["state_digest"]:
        add("replay-mismatch", "reduce(start_state, event_batch) != committed resulting_state")

    # recomputation
    seed = rec["rng"]["master_seed"] if rec.get("rng") else 0
    try:
        recomputed = rsv.transition(rec["start_state"], rec["command_batch"],
                                    master_seed=seed, turn=rec["turn"])
    except Exception as exc:  # noqa: BLE001
        add("recompute-failed", f"transition raised: {exc}")
        return problems
    if canon.canonical_bytes(recomputed["events"]) != canon.canonical_bytes(rec["event_batch"]):
        add("recompute-event-mismatch", "recomputed event_batch != committed")
    if canon.canonical_bytes(recomputed["resulting_state"]["state"]) \
            != canon.canonical_bytes(rec["resulting_state"]["state"]):
        add("recompute-state-mismatch", "recomputed resulting state != committed")

    # draw -> event coherence (each stochastic terminal references exactly one draw, and vice versa)
    stochastic = [e for e in rec["event_batch"] if e["event_type"] in _TERMINALS and e.get("draw_ref")]
    if len(stochastic) != len(rec.get("draw_records", [])):
        add("draw-event-count", "stochastic-terminal count != draw count")
    return problems


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate_turn_replay.py")
    parser.add_argument("paths", nargs="*",
                        help="turn-record files (default: glob examples/**/run/turns/*.json)")
    args = parser.parse_args(argv)
    files = [Path(p) for p in args.paths] if args.paths \
        else sorted(REPO_ROOT.glob("examples/**/run/turns/*.json"))
    if not files:
        print("error: no committed turn records (examples/**/run/turns/*.json); refusing to report clean.",
              file=sys.stderr)
        return 2

    findings: list = []
    for path in files:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"error: cannot read {path}: {exc}; refusing to report clean.", file=sys.stderr)
            return 2
        try:
            where = str(path.relative_to(REPO_ROOT))
        except ValueError:
            where = str(path)
        findings.extend(check_record(rec, where))

    if findings:
        print(f"turn-replay FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1
    print(f"turn-replay OK ({len(files)} turn record(s) replayed + recomputed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

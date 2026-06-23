"""WP-E2b2 multi-turn campaign orchestrator — deterministic chaining over the heterogeneous salvo.

Chains weekly turns: each turn's ``resulting_state`` (which carries the in-``reduce`` ``as_of_turn``
advance via the ``TURN_ADVANCED`` event) becomes the next turn's ``start_state`` BYTE-IDENTICALLY — so the
committed chain ``run/turns/0000.json .. NNNN.json`` has digest-identical head handoffs (the continuity
invariant the turn-replay chain pass enforces). Stops at culmination or the week horizon. No RNG, no
commands. Reuses ``turn_record.assemble``/``commit`` (+ ``atomic`` O_EXCL): re-running is idempotent on
byte-identical records and a ``SlotConflict`` on a changed ruleset. Mirrors ``scripts/salvo_het_run.py``.

``run_campaign`` is PURE (no I/O) so it is unit-testable into tmp; ``commit_campaign`` does the durable
writes. Usage: ``python scripts/campaign_run.py [--write] [--weeks N]`` (default: print the trajectory).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))

import salvo_resolver_het as salvo_het  # noqa: E402
import turn_record as tr  # noqa: E402
from salvo_het_run import _flatten  # noqa: E402  (reuse the {value,source} -> int-only flattener)

SCENARIO = ROOT / "examples" / "ru_ua_salvo_multiturn"
MAX_WEEKS = 12
FIXED_FINGERPRINT = {"engine_source_hash": "wpe2b2-campaign", "python": "fixed", "pyyaml_version": "fixed",
                     "serializer_version": "1", "persistence_profile": "local-posix-fs-v1"}


def load_scenario(scenario_dir: Path = SCENARIO) -> tuple[dict, dict]:
    state = yaml.safe_load((scenario_dir / "engine_state.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((scenario_dir / "rules.yaml").read_text(encoding="utf-8"))
    return state, _flatten(rules["params"])


def _culminated(rec: dict) -> bool:
    return any(e["event_type"] == "CULMINATION_STATUS" and e["culminated"] for e in rec["event_batch"])


def run_campaign(start_state: dict, ruleset: dict, max_weeks: int = MAX_WEEKS) -> tuple[list, str]:
    """Chain up to max_weeks turns; return (records, stop_reason). PURE — no I/O. The week index comes
    from ``head.state.as_of_turn`` (the state is the authority), not a Python counter."""
    head = start_state
    records: list = []
    stop_reason = "reached-horizon"
    for _ in range(max_weeks):
        turn = head["state"]["as_of_turn"]
        out = tr.assemble(turn=turn, start_state=head, commands=[], master_seed=0,
                          runtime_fingerprint=FIXED_FINGERPRINT,
                          successor_slot=f"run/turns/{turn + 1:04d}.json",
                          ruleset=ruleset, resolver=salvo_het)
        rec = out["turn_record"]
        records.append(rec)
        head = rec["resulting_state"]          # the sealed envelope -> the next start_state, byte-identical
        if _culminated(rec):
            stop_reason = "culminated"
            break
    return records, stop_reason


def commit_campaign(records: list, scenario_dir: Path = SCENARIO) -> list:
    """Commit each record to run/turns/{turn:04d}.json (O_EXCL, idempotent-or-SlotConflict)."""
    results: list = []
    for rec in records:
        slot = scenario_dir / "run" / "turns" / f"{rec['turn']:04d}.json"
        slot.parent.mkdir(parents=True, exist_ok=True)
        results.append(tr.commit(rec, str(slot)))
    return results


def _row(rec: dict) -> str:
    ev = {e["event_type"]: e for e in rec["event_batch"]}
    leth, mag, culm = ev.get("LETHALITY_STATUS", {}), ev.get("MAGAZINE_STATUS", {}), ev.get("CULMINATION_STATUS", {})
    leaked = sum(e["count"] for e in rec["event_batch"] if e["event_type"] == "STRIKES_LEAKED")
    return (f"  wk{rec['turn']:2d}  eff={leth.get('effective_intercept_pct')}%  leaked={leaked}  "
            f"streak={leth.get('streak')}  mag_weeks={mag.get('weeks_remaining')} "
            f"depleted={mag.get('magazine_depleted')}  culminated={culm.get('culminated')}")


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="campaign_run.py")
    parser.add_argument("--write", action="store_true", help="commit the campaign turn records")
    parser.add_argument("--weeks", type=int, default=MAX_WEEKS)
    args = parser.parse_args(argv)
    state, ruleset = load_scenario()
    records, stop_reason = run_campaign(state, ruleset, max_weeks=args.weeks)
    if args.write:
        results = commit_campaign(records)
        print(f"campaign: {len(records)} week(s), stop={stop_reason}; commits={results}")
    else:
        for rec in records:
            print(_row(rec))
        print(f"  stop={stop_reason} after {len(records)} week(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

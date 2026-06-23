"""WP-E2b2 culmination-as-RANGE sensitivity sweep — a DERIVED report, NOT a gate.

Runs the multi-turn campaign over a one-at-a-time **resupply** sweep {-100, -50, 0, +100, +200}% (scaling
every interceptor's ``weekly_resupply``, integer) and reports the culmination week per cell — so
culmination timing is presented as a RANGE, not a single point. The band is deliberately WIDE: with the
WP-E2b3 per-class lethality culmination (the pooled inventory limb dropped), the culmination week is
governed by the magazine DEPTH that paces interceptor depletion, so a narrow +-50% resupply band sits in a
flat region (all wk6) and a wider sweep is needed to exercise the genuine sensitivity (wk5 at zero resupply
to wk8 at 3x; resupply beyond ~+300% prevents culmination within the horizon). ``run_campaign`` is pure, so
this commits NOTHING (only the BASE campaign is committed, by campaign_run). Each cell records a
``config_hash`` (canon digest of the perturbed start_state + ruleset), the seed, the ``code_version``, and
an ``as_of_date`` for reproducibility. Integer scaling stays canon-safe.

Output is on demand: ``python scripts/campaign_sensitivity.py`` prints the report; ``--write`` saves a
(git-ignored-by-convention, regenerable) ``campaign_sensitivity.json``. ILLUSTRATIVE / UNCALIBRATED.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))

import canon  # noqa: E402
import campaign_run as cr  # noqa: E402

FACTORS_PCT = (-100, -50, 0, 100, 200)


def _scaled(state: dict, factor_pct: int) -> dict:
    """A deep copy with every interceptor ``weekly_resupply`` scaled by (100+factor_pct)% (integer)."""
    s = copy.deepcopy(state)
    for ent in s["state"]["entities"]:
        if ent["id"].startswith("ukraine_intc_"):
            base = ent["fields"]["weekly_resupply"]["value"]
            ent["fields"]["weekly_resupply"]["value"] = base * (100 + factor_pct) // 100
    return s


def _code_version() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def sweep(as_of_date: str | None = None, max_weeks: int = cr.MAX_WEEKS) -> dict:
    state, ruleset = cr.load_scenario()
    code_version = _code_version()
    cells = []
    for factor in FACTORS_PCT:
        perturbed = _scaled(state, factor)
        records, reason = cr.run_campaign(perturbed, ruleset, max_weeks=max_weeks)
        culm_week = records[-1]["turn"] if reason == "culminated" else None
        cells.append({
            "resupply_factor_pct": factor,
            "culmination_week": culm_week,
            "outcome": "culminated" if culm_week is not None else f"never within {max_weeks} weeks",
            "config_hash": canon.canonical_digest({"start_state": perturbed["state"], "ruleset": ruleset}),
            "master_seed": 0,
            "code_version": code_version,
            "as_of_date": as_of_date,
        })
    weeks = [c["culmination_week"] for c in cells if c["culmination_week"] is not None]
    return {
        "report": "WP-E2b2 culmination-as-range sensitivity sweep (DERIVED; ILLUSTRATIVE / UNCALIBRATED)",
        "scenario": "ru_ua_salvo_multiturn",
        "swept_input": "interceptor weekly_resupply (one-at-a-time)",
        "horizon_weeks": max_weeks,
        "culmination_week_range": [min(weeks), max(weeks)] if weeks else None,
        "headline": ("Culmination timing shifts with the resupply assumption (wk5 at zero resupply to wk8 "
                     "at +200%), reported as a RANGE not a point. Within +-50% it is ROBUST at the committed "
                     "wk6: under per-class lethality culmination, resupply FLOW is a weaker lever than the "
                     "magazine DEPTH that paces interceptor depletion. UNCALIBRATED."),
        "cells": cells,
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="campaign_sensitivity.py")
    parser.add_argument("--write", action="store_true", help="write campaign_sensitivity.json (regenerable)")
    parser.add_argument("--as-of-date", default=None, help="stamp the report (default: null)")
    args = parser.parse_args(argv)
    report = sweep(args.as_of_date)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.write:
        out = cr.SCENARIO / "campaign_sensitivity.json"
        out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

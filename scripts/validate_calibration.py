#!/usr/bin/env python3
"""Centaur calibration validator (WP9.1, the evidence-or-label gate for calibration).

CONSTITUTION §5 applied to calibration: a scenario whose signoff declares
`calibration_status: CALIBRATED` must back that claim with a calibration **record**
(`examples/<scenario>/calibration.yaml`) carrying minimal proper-scoring-rule provenance;
`UNCALIBRATED` / `ILLUSTRATIVE` (the honest "UNCALIBRATED ANALYTICAL JUDGMENT" label) need
no record. **The harness RECORDS an externally / human-computed calibration result; it never
COMPUTES one** -- scoring needs the engine + resolved outcomes (a non-goal, like turn-replay).

  - evidence-or-label: CALIBRATED with no record -> `unsupported-calibration` (blocks release,
    like §5 `unsupported-baseline`); a record present under a non-CALIBRATED status -> a
    `consistency-note` (reconcile the status or remove the record);
  - structure: the record is a flat mapping with proper-scoring provenance (metric enum +
    a finite, in-range metric_value; a positive integer outcome_count; an ISO scoring_date);
  - reproducibility binding: the record pins the scenario run_ledger's `code_version` -- a
    declared-input drift regenerates the ledger and makes the record `stale-calibration`
    (re-score / re-record), extending the WP7 lockfile discipline.

STRUCTURAL + ATTESTATION ONLY: a clean result means the calibration *claim* is evidence-backed
and current, NOT that the analysis is valid. Composed into `verify.py --mode release`.

Usage:
    python scripts/validate_calibration.py                          # the Ukraine example
    python scripts/validate_calibration.py --scenario-dir DIR       # DIR/{signoff,run_ledger,scenario,calibration}.yaml
    python scripts/validate_calibration.py --signoff S --calibration C --scenario-dir DIR

Exit codes: 0 = ok (claim backed, or no claim made), 1 = findings (structure / resolution /
unsupported / consistency), 2 = usage / fail-closed (a missing/unreadable signoff/ledger/scenario,
or a CALIBRATED claim whose present record cannot be parsed).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from validate_schemas import (
    REPO_ROOT,
    _display,
    _is_nonempty_str,
    _valid_iso_date,
    _validate_skeleton,
)
from validate_claims import load_registry

DEFAULT_SCENARIO = REPO_ROOT / "examples" / "ukraine_crimea_logistics"

# Only CALIBRATED requires a record; the other two are honest no-evidence labels (§5).
REQUIRES_RECORD = "CALIBRATED"
NO_RECORD_STATUSES = ("UNCALIBRATED", "ILLUSTRATIVE")

# Metric value ranges per published scoring-rule definitions -- NOT magic numbers:
# Brier 1950 (mean squared error of probability forecasts) and HIT_RATE (GJP/Tetlock
# fraction-correct) are bounded in [0, 1]; the logarithmic score is in [0, +inf).
METRIC_RANGES = {
    "BRIER_SCORE": (0.0, 1.0),
    "HIT_RATE": (0.0, 1.0),
    "LOG_LOSS": (0.0, math.inf),
}
METRIC_ENUM = tuple(METRIC_RANGES)  # single source for the spec + the range checks

# Enum fields live ONLY in `enums`; outcome_count is an int; metric_value/baseline_value are
# floats checked separately (the skeleton handles flat strings/ints/enums only).
CALIBRATION_SPEC = {
    "required_str": ("schema_version", "id", "target", "code_version",
                     "outcome_authority", "scoring_date", "forecaster"),
    "required_int": ("outcome_count",),
    "enums": {"metric": METRIC_ENUM},
}


def _usable_doc(doc: object) -> bool:
    """A usable record is a NON-EMPTY mapping (an empty/null doc is fail-closed)."""
    return isinstance(doc, dict) and bool(doc)


def _is_finite_number(value: object) -> bool:
    """A real, finite number -- rejects bool, NaN, +/-Inf, and non-numerics. The probability
    check in validate_schemas does not catch NaN/Inf (nan <= 1.0 is False), so be explicit."""
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _range_problem(field: str, value: object, metric: object, where: str) -> tuple | None:
    """Return an (invalid-range) problem if a finite numeric `value` is outside the metric's
    published range. Only runs for a VALID metric (else the enum check owns the finding)."""
    if metric in METRIC_RANGES and _is_finite_number(value):
        lo, hi = METRIC_RANGES[metric]
        if not (lo <= value <= hi):
            hi_s = "inf" if hi == math.inf else hi
            return ("invalid-range", where,
                    f"{field} {value} is out of range [{lo}, {hi_s}] for metric {metric}")
    return None


def _structural_problems(cdoc: dict, where: str) -> list[tuple[str, str, str]]:
    """Structure of the calibration record (skeleton + the numeric/date checks it omits)."""
    problems: list[tuple[str, str, str]] = list(_validate_skeleton(cdoc, where, CALIBRATION_SPEC))

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    metric = cdoc.get("metric")

    # metric_value: a finite number in the metric's range (a float -> not in the skeleton).
    mv = cdoc.get("metric_value")
    if mv is None:
        add("missing-field", "metric_value is required")
    elif not _is_finite_number(mv):
        add("wrong-type", f"metric_value must be a finite number; got {mv!r}")
    else:
        rp = _range_problem("metric_value", mv, metric, where)
        if rp:
            problems.append(rp)

    # outcome_count: the skeleton enforces int-not-bool; this adds N > 0.
    oc = cdoc.get("outcome_count")
    if isinstance(oc, int) and not isinstance(oc, bool) and oc <= 0:
        add("invalid-range", f"outcome_count must be > 0 (a calibration over N={oc} is not auditable)")

    # baseline_value: optional; if present, a finite number in the same range.
    bv = cdoc.get("baseline_value")
    if bv is not None:
        if not _is_finite_number(bv):
            add("wrong-type", f"baseline_value, if present, must be a finite number; got {bv!r}")
        else:
            rp = _range_problem("baseline_value", bv, metric, where)
            if rp:
                problems.append(rp)

    # scoring_date: required_str catches absent; this catches a present-but-malformed value.
    scoring_date = cdoc.get("scoring_date")
    if _is_nonempty_str(scoring_date) and not _valid_iso_date(scoring_date):
        add("invalid-format", f"scoring_date {scoring_date!r} must be an ISO-8601 date (YYYY-MM-DD)")

    return problems


def _resolution_problems(cdoc: dict, ledger_cv: str, scenario_name: str,
                         where: str) -> list[tuple[str, str, str]]:
    """Scenario + ledger binding. Assumes structure passed (so fixtures stay single-fault)."""
    problems: list[tuple[str, str, str]] = []
    if cdoc["target"] != scenario_name:
        problems.append(("unresolved-scenario-ref", where,
                         f"target {cdoc['target']!r} does not name this scenario ({scenario_name!r})"))
    if cdoc["code_version"] != ledger_cv:
        problems.append(("stale-calibration", where,
                         f"calibration code_version {cdoc['code_version'][:12]}... != run-ledger "
                         f"{ledger_cv[:12]}...; re-score / re-record the current snapshot"))
    return problems


def _fail_closed(reason: str) -> int:
    print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
    return 2


def _report(problems: list[tuple[str, str, str]]) -> int:
    print(f"calibration validation FAILED: {len(problems)} problem(s):", file=sys.stderr)
    for code, where, msg in problems:
        print(f"  - {code}  {where}  {msg}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_calibration.py",
        description="Validate a scenario's calibration claim: evidence-or-label (the release gate).",
    )
    parser.add_argument("--scenario-dir", default=str(DEFAULT_SCENARIO),
                        help="scenario dir holding signoff/run_ledger/scenario/calibration (default: Ukraine example)")
    parser.add_argument("--signoff", default=None, help="signoff.yaml path (default: <scenario-dir>/signoff.yaml)")
    parser.add_argument("--calibration", default=None,
                        help="calibration.yaml path (default: <scenario-dir>/calibration.yaml)")
    args = parser.parse_args(argv)

    scenario_dir = Path(args.scenario_dir).resolve()
    signoff_path = Path(args.signoff).resolve() if args.signoff else scenario_dir / "signoff.yaml"
    calibration_path = Path(args.calibration).resolve() if args.calibration else scenario_dir / "calibration.yaml"
    ledger_path = scenario_dir / "run_ledger.yaml"

    # Fail-closed: a missing scenario / ledger / signoff cannot be judged.
    if not (scenario_dir / "scenario.yaml").is_file():
        return _fail_closed(f"{scenario_dir}/scenario.yaml is absent (no scenario to attest)")
    ldoc, lerr = load_registry(ledger_path)
    if lerr is not None or not isinstance(ldoc, dict) or not _is_nonempty_str(ldoc.get("code_version")):
        return _fail_closed(lerr or f"{ledger_path} is not a usable run-ledger (need a code_version)")
    sdoc, serr = load_registry(signoff_path)
    if serr is not None or not _usable_doc(sdoc):
        return _fail_closed(serr or f"{signoff_path} is not a usable signoff (need a non-empty mapping)")
    status = sdoc.get("calibration_status")
    if not _is_nonempty_str(status):
        return _fail_closed(f"{signoff_path} has no usable calibration_status (the signoff gate owns the enum)")

    cal_where = _display(calibration_path)
    record_present = calibration_path.is_file()

    # Evidence-or-label branch (the signoff gate validates the status enum itself).
    if status == REQUIRES_RECORD:
        if not record_present:
            return _report([("unsupported-calibration", _display(signoff_path),
                             "calibration_status is CALIBRATED but no calibration.yaml record is "
                             "present; provide the record or declare UNCALIBRATED / ILLUSTRATIVE")])
        cdoc, cerr = load_registry(calibration_path)
        if cerr is not None or not _usable_doc(cdoc):
            return _fail_closed(cerr or f"{calibration_path} is present but not a usable record (non-empty mapping)")
        # Structure first; on a structural fault STOP (so fixtures stay single-fault).
        problems = _structural_problems(cdoc, cal_where)
        if not problems:
            problems = _resolution_problems(cdoc, ldoc["code_version"], scenario_dir.name, cal_where)
        if problems:
            return _report(problems)
        print(f"calibration validation OK (CALIBRATED, {cdoc['metric']} {cdoc['metric_value']}, "
              f"N={cdoc['outcome_count']})")
        return 0

    if status in NO_RECORD_STATUSES:
        if record_present:
            # A record under a no-evidence label is a contradiction -- reconcile, do not lurk.
            return _report([("consistency-note", cal_where,
                             f"a calibration.yaml record is present but calibration_status is {status}; "
                             "remove the record or declare CALIBRATED")])
        print(f"calibration validation OK ({status}, no record required)")
        return 0

    # An out-of-enum status: the signoff gate reports the bad enum; calibration cannot judge.
    return _fail_closed(f"calibration_status {status!r} is not a recognized value")


if __name__ == "__main__":
    raise SystemExit(main())

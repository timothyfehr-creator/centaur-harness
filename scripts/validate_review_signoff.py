#!/usr/bin/env python3
"""Centaur review + signoff validator (WP8.1, the attestation gate for `release`).

A scenario is releasable only if it carries an adversarial **review** (refuter verdict)
and a human **signoff**, both bound to the reproducible snapshot the run-ledger pins. This
gate validates the two per-scenario attestation artifacts and the chain between them:

  - structure: each is a flat mapping with its required fields + enums
    (`review.verdict` in ACCEPT/REVISE; `signoff.decision` in APPROVED/REJECTED;
    `signoff.calibration_status` in UNCALIBRATED/ILLUSTRATIVE -- a DECLARED honest status,
    not an executed calibration, which is WP9);
  - resolution: `review.target` names this scenario; `signoff.review_ref` resolves to the
    review's id;
  - reproducibility binding: BOTH attestations pin the scenario run_ledger's `code_version`
    -- when a declared input drifts and the ledger is regenerated to a new code_version, the
    attestation goes STALE (`stale-attestation`) and must be re-reviewed / re-signed. This
    extends the WP7 lockfile discipline to approvals;
  - honesty: a refuter `REVISE` (`revise-verdict`) or a human `REJECTED` (`rejected-decision`)
    BLOCKS release -- releasing either would be a CONSTITUTION §3 false-pass.

STRUCTURAL + ATTESTATION ONLY: a clean result means the package is complete and attested, NOT
that the analysis is valid. Composed into `verify.py --mode release` (WP8.2).

Usage:
    python scripts/validate_review_signoff.py                       # the Ukraine example
    python scripts/validate_review_signoff.py --scenario-dir DIR    # DIR/{review,signoff,run_ledger,scenario}.yaml
    python scripts/validate_review_signoff.py --review R --signoff S --scenario-dir DIR

Exit codes: 0 = attested, 1 = findings (structure / resolution / staleness / blocked),
2 = usage / fail-closed (a missing / unreadable / empty attestation, or a broken/absent
run-ledger or scenario -- attestation over nothing must never report clean).
"""
from __future__ import annotations

import argparse
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

# Enum fields live ONLY in `enums` (an absent enum is missing-field, a present out-of-set
# value is invalid-enum); non-enum required strings live in `required_str`. `findings`
# (a list) and `date` (ISO) are checked separately below -- the skeleton handles flat
# strings/ints/enums only.
REVIEW_SPEC = {
    "required_str": ("schema_version", "id", "target", "code_version", "reviewer"),
    "required_int": (),
    "enums": {"verdict": ("ACCEPT", "REVISE")},
}
SIGNOFF_SPEC = {
    "required_str": ("schema_version", "id", "review_ref", "code_version", "signed_by", "date"),
    "required_int": (),
    "enums": {
        "decision": ("APPROVED", "REJECTED"),
        "calibration_status": ("UNCALIBRATED", "ILLUSTRATIVE"),
    },
}


def _usable_doc(doc: object) -> bool:
    """A usable attestation is a NON-EMPTY mapping. An empty doc ({} / null) is fail-closed,
    never 'no findings == clean' -- the zero-attestation fail-open (AGENTS.md)."""
    return isinstance(doc, dict) and bool(doc)


def _structural_problems(rdoc: dict, sdoc: dict, review_where: str,
                         signoff_where: str) -> list[tuple[str, str, str]]:
    """Structure of both attestations (skeleton + the list/date checks the skeleton omits)."""
    problems: list[tuple[str, str, str]] = []
    problems.extend(_validate_skeleton(rdoc, review_where, REVIEW_SPEC))
    # findings: a list with >=1 non-empty string (an absent / empty / all-blank list is the
    # same defect -- there is nothing to review).
    findings = rdoc.get("findings")
    items = [f for f in findings if _is_nonempty_str(f)] if isinstance(findings, list) else []
    if not items:
        problems.append(("empty-findings", review_where,
                         "findings must be a list with at least one non-empty string"))
    problems.extend(_validate_skeleton(sdoc, signoff_where, SIGNOFF_SPEC))
    # date: required_str catches absent; this catches a present-but-malformed value.
    date = sdoc.get("date")
    if _is_nonempty_str(date) and not _valid_iso_date(date):
        problems.append(("invalid-format", signoff_where,
                         f"date {date!r} must be an ISO-8601 date (YYYY-MM-DD)"))
    return problems


def _resolution_problems(rdoc: dict, sdoc: dict, ledger_cv: str, scenario_name: str,
                         review_where: str, signoff_where: str) -> list[tuple[str, str, str]]:
    """Cross-refs + ledger-binding + honesty. Assumes structure already passed, so every
    fixture trips exactly one of these (the others stay valid)."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, where: str, msg: str) -> None:
        problems.append((code, where, msg))

    if rdoc["target"] != scenario_name:
        add("unresolved-scenario-ref", review_where,
            f"target {rdoc['target']!r} does not name this scenario ({scenario_name!r})")
    if sdoc["review_ref"] != rdoc["id"]:
        add("unresolved-review-ref", signoff_where,
            f"review_ref {sdoc['review_ref']!r} does not resolve to the review id {rdoc['id']!r}")
    if rdoc["code_version"] != ledger_cv:
        add("stale-attestation", review_where,
            f"review code_version {rdoc['code_version'][:12]}... != run-ledger "
            f"{ledger_cv[:12]}...; re-review the current snapshot")
    if sdoc["code_version"] != ledger_cv:
        add("stale-attestation", signoff_where,
            f"signoff code_version {sdoc['code_version'][:12]}... != run-ledger "
            f"{ledger_cv[:12]}...; re-sign the current snapshot")
    if rdoc["verdict"] == "REVISE":
        add("revise-verdict", review_where,
            "review verdict is REVISE -- the refuter wants changes; release is blocked until "
            "the scenario is revised and re-reviewed to ACCEPT")
    if sdoc["decision"] == "REJECTED":
        add("rejected-decision", signoff_where,
            "signoff decision is REJECTED -- release is blocked")
    return problems


def _fail_closed(reason: str) -> int:
    print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_review_signoff.py",
        description="Validate a scenario's review + signoff attestations (the release gate).",
    )
    parser.add_argument("--scenario-dir", default=str(DEFAULT_SCENARIO),
                        help="scenario dir holding review/signoff/run_ledger/scenario (default: Ukraine example)")
    parser.add_argument("--review", default=None, help="review.yaml path (default: <scenario-dir>/review.yaml)")
    parser.add_argument("--signoff", default=None, help="signoff.yaml path (default: <scenario-dir>/signoff.yaml)")
    args = parser.parse_args(argv)

    scenario_dir = Path(args.scenario_dir).resolve()
    review_path = Path(args.review).resolve() if args.review else scenario_dir / "review.yaml"
    signoff_path = Path(args.signoff).resolve() if args.signoff else scenario_dir / "signoff.yaml"
    ledger_path = scenario_dir / "run_ledger.yaml"

    # Fail-closed: a missing scenario / ledger / attestation cannot be judged.
    if not (scenario_dir / "scenario.yaml").is_file():
        return _fail_closed(f"{scenario_dir}/scenario.yaml is absent (no scenario to attest)")
    ldoc, lerr = load_registry(ledger_path)
    if lerr is not None or not isinstance(ldoc, dict) or not _is_nonempty_str(ldoc.get("code_version")):
        return _fail_closed(lerr or f"{ledger_path} is not a usable run-ledger (need a code_version)")
    rdoc, rerr = load_registry(review_path)
    if rerr is not None or not _usable_doc(rdoc):
        return _fail_closed(rerr or f"{review_path} is not a usable review (need a non-empty mapping)")
    sdoc, serr = load_registry(signoff_path)
    if serr is not None or not _usable_doc(sdoc):
        return _fail_closed(serr or f"{signoff_path} is not a usable signoff (need a non-empty mapping)")

    review_where, signoff_where = _display(review_path), _display(signoff_path)

    # Structure first; on a structural fault STOP (so structural fixtures stay single-fault
    # and resolution never runs against a malformed attestation).
    problems = _structural_problems(rdoc, sdoc, review_where, signoff_where)
    if not problems:
        problems = _resolution_problems(rdoc, sdoc, ldoc["code_version"], scenario_dir.name,
                                        review_where, signoff_where)

    if problems:
        print(f"review/signoff validation FAILED: {len(problems)} problem(s):", file=sys.stderr)
        for code, where, msg in problems:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"review/signoff validation OK (verdict {rdoc['verdict']}, decision "
          f"{sdoc['decision']}, calibration {sdoc['calibration_status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

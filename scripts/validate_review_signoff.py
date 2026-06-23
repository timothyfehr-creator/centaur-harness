#!/usr/bin/env python3
"""Centaur review + signoff validator (WP8.1, the attestation gate for `release`).

A scenario is releasable only if it carries an adversarial **review** (refuter verdict)
and a human **signoff**, both bound to the reproducible snapshot the run-ledger pins. This
gate validates the two per-scenario attestation artifacts and the chain between them:

  - structure: each is a flat mapping with its required fields + enums. `attestation_kind` in
    INDEPENDENT/SYNTHETIC_SELF_CHECK PARTITIONS the legal verdict/decision: an INDEPENDENT attestation may
    ACCEPT/APPROVE; a SYNTHETIC_SELF_CHECK (the loop checking its own work) may only SELF_CHECK_PASSED /
    EXTERNAL_REVIEW_PENDING (or *_REVISE / SELF_CHECK_FAILED) -- it CANNOT spell APPROVED/ACCEPT, so a
    self-approval can never be mistaken for an independent attestation. `signoff.calibration_status` in
    UNCALIBRATED/ILLUSTRATIVE/CALIBRATED -- the CALIBRATED posture must resolve to a calibration record
    (WP9, `validate_calibration.py`);
  - resolution: `review.target` names this scenario; `signoff.review_ref` resolves to the review's id; the
    two attestations' `attestation_kind` must agree; an INDEPENDENT attestation whose signer/reviewer reads
    as automated is a `self-attested-independence` lie;
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
    "enums": {
        "attestation_kind": ("INDEPENDENT", "SYNTHETIC_SELF_CHECK"),
        "verdict": ("ACCEPT", "REVISE", "SELF_CHECK_PASSED", "SELF_CHECK_REVISE"),
    },
}
SIGNOFF_SPEC = {
    "required_str": ("schema_version", "id", "review_ref", "code_version", "signed_by", "date"),
    "required_int": (),
    "enums": {
        "attestation_kind": ("INDEPENDENT", "SYNTHETIC_SELF_CHECK"),
        "decision": ("APPROVED", "REJECTED", "EXTERNAL_REVIEW_PENDING", "SELF_CHECK_FAILED"),
        # WP9: CALIBRATED requires a resolving calibration.yaml (enforced by
        # validate_calibration.py); UNCALIBRATED / ILLUSTRATIVE need no record.
        "calibration_status": ("UNCALIBRATED", "ILLUSTRATIVE", "CALIBRATED"),
        # WP-E2c.1 #2: the approver DECLARES the calibration disposition. A feasibility verdict
        # (NOT_FEASIBLE / INSUFFICIENT_DATA) obliges a bound calibration_feasibility.yaml (ref + sha256,
        # cross-checked by validate_calibration_feasibility.py) -- so deleting the record fails release.
        "calibration_disposition": ("NONE", "NOT_FEASIBLE", "INSUFFICIENT_DATA", "CALIBRATED"),
    },
}
_FEASIBILITY_DISPOSITIONS = ("NOT_FEASIBLE", "INSUFFICIENT_DATA")


def _is_hex64(s: object) -> bool:
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s)

# attestation_kind PARTITIONS the legal decision/verdict values. An INDEPENDENT attestation (a human or a
# genuinely independent reviewer) can APPROVE / ACCEPT; a SYNTHETIC_SELF_CHECK (the loop checking its own
# work) structurally CANNOT spell APPROVED / ACCEPT -- only "self-check passed, pending independent review"
# or "self-check failed". This is what makes a self-approval impossible to mistake for an independent
# attestation: the disclaimer is a PARSED ENUM, not a YAML comment that evaporates on load.
_LEGAL_DECISION = {
    "INDEPENDENT": ("APPROVED", "REJECTED"),
    "SYNTHETIC_SELF_CHECK": ("EXTERNAL_REVIEW_PENDING", "SELF_CHECK_FAILED"),
}
_LEGAL_VERDICT = {
    "INDEPENDENT": ("ACCEPT", "REVISE"),
    "SYNTHETIC_SELF_CHECK": ("SELF_CHECK_PASSED", "SELF_CHECK_REVISE"),
}
_BLOCKING_DECISION = ("REJECTED", "SELF_CHECK_FAILED")     # -> exit 1 (release blocked)
_BLOCKING_VERDICT = ("REVISE", "SELF_CHECK_REVISE")
# An attestation_kind: INDEPENDENT signoff/review is honored ONLY if its signer/reviewer is in the
# HUMAN-CONTROLLED independent-reviewer allow-list. A regex heuristic is NOT a security boundary (a synthetic
# signer that dodges a few words evades it); a positive allow-list is. The list starts EMPTY: until a human
# adds a genuinely-independent reviewer, nothing can be INDEPENDENT, so every attestation must be a
# SYNTHETIC_SELF_CHECK. (The loop adding itself to the list is a conspicuous, merge-reviewable change.)
INDEPENDENT_REVIEWERS_DEFAULT = REPO_ROOT / "attestation_reviewers.yaml"


def _load_independent_reviewers(path: Path) -> set[str]:
    """The allow-listed independent-reviewer identities. Absent / unreadable / malformed -> the EMPTY set
    (strict: no INDEPENDENT attestation is honored), never a fail-open."""
    doc, err = load_registry(path)
    if err is not None or not isinstance(doc, dict):
        return set()
    listed = doc.get("independent_reviewers")
    return {x for x in listed if _is_nonempty_str(x)} if isinstance(listed, list) else set()


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
                         review_where: str, signoff_where: str,
                         reviewers: set[str]) -> list[tuple[str, str, str]]:
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
    # attestation_kind must AGREE across the two artifacts, and each kind permits only its own
    # decision/verdict values -- so a SYNTHETIC_SELF_CHECK can never spell APPROVED/ACCEPT.
    rkind, skind = rdoc["attestation_kind"], sdoc["attestation_kind"]
    if rkind != skind:
        add("kind-mismatch", signoff_where,
            f"review attestation_kind {rkind!r} != signoff attestation_kind {skind!r}")
    else:
        if rdoc["verdict"] not in _LEGAL_VERDICT[rkind]:
            add("kind-verdict-mismatch", review_where,
                f"verdict {rdoc['verdict']!r} is not legal for a {rkind} review "
                f"(legal: {list(_LEGAL_VERDICT[rkind])})")
        if sdoc["decision"] not in _LEGAL_DECISION[skind]:
            add("kind-decision-mismatch", signoff_where,
                f"decision {sdoc['decision']!r} is not legal for a {skind} signoff "
                f"(legal: {list(_LEGAL_DECISION[skind])})")
    # an INDEPENDENT attestation is honored ONLY if its reviewer/signer is in the human-controlled allow-list
    # -- a self-check cannot mint its own independence by self-declaring the kind.
    if rkind == "INDEPENDENT" and rdoc["reviewer"] not in reviewers:
        add("unlisted-independent-reviewer", review_where,
            f"attestation_kind is INDEPENDENT but reviewer {rdoc['reviewer']!r} is not in the "
            f"independent-reviewer allow-list")
    if skind == "INDEPENDENT" and sdoc["signed_by"] not in reviewers:
        add("unlisted-independent-reviewer", signoff_where,
            f"attestation_kind is INDEPENDENT but signed_by {sdoc['signed_by']!r} is not in the "
            f"independent-reviewer allow-list")
    # disposition obligation (#2): a feasibility verdict MUST carry a ref + a 64-hex sha256 binding the
    # calibration_feasibility.yaml record (the cross-check that the record exists + is unedited lives in
    # validate_calibration_feasibility.py; here we enforce the signoff carries the binding at all).
    if sdoc["calibration_disposition"] in _FEASIBILITY_DISPOSITIONS:
        if not _is_nonempty_str(sdoc.get("calibration_feasibility_ref")):
            add("missing-field", signoff_where,
                f"calibration_feasibility_ref is required when calibration_disposition is "
                f"{sdoc['calibration_disposition']} (it must name the feasibility record's id)")
        if not _is_hex64(sdoc.get("calibration_feasibility_sha256")):
            add("invalid-format", signoff_where,
                f"calibration_feasibility_sha256 must be 64 lowercase hex when calibration_disposition is "
                f"{sdoc['calibration_disposition']} (it binds the feasibility record's exact bytes)")

    # honesty blocks: a refuter wanting changes / a failed self-check / a REJECTED human signoff block release
    if rdoc["verdict"] in _BLOCKING_VERDICT:
        add("revise-verdict" if rdoc["verdict"] == "REVISE" else "self-check-revise", review_where,
            f"review verdict is {rdoc['verdict']} -- changes wanted; release is blocked until re-reviewed")
    if sdoc["decision"] in _BLOCKING_DECISION:
        add("rejected-decision" if sdoc["decision"] == "REJECTED" else "self-check-failed", signoff_where,
            f"signoff decision is {sdoc['decision']} -- release is blocked")
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
    parser.add_argument("--reviewers", default=str(INDEPENDENT_REVIEWERS_DEFAULT),
                        help="independent-reviewer allow-list (default: repo attestation_reviewers.yaml)")
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
    reviewers = _load_independent_reviewers(Path(args.reviewers).resolve())

    # Structure first; on a structural fault STOP (so structural fixtures stay single-fault
    # and resolution never runs against a malformed attestation).
    problems = _structural_problems(rdoc, sdoc, review_where, signoff_where)
    if not problems:
        problems = _resolution_problems(rdoc, sdoc, ldoc["code_version"], scenario_dir.name,
                                        review_where, signoff_where, reviewers)

    if problems:
        print(f"review/signoff validation FAILED: {len(problems)} problem(s):", file=sys.stderr)
        for code, where, msg in problems:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"review/signoff validation OK (kind {sdoc['attestation_kind']}, verdict {rdoc['verdict']}, "
          f"decision {sdoc['decision']}, calibration {sdoc['calibration_status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

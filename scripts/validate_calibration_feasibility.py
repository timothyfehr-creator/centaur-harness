#!/usr/bin/env python3
"""Centaur calibration-FEASIBILITY validator (WP-E2c).

The honest companion to the evidence-or-label calibration gate: a scenario may commit a
`calibration_feasibility.yaml` recording that a channel was ATTEMPTED for calibration and CANNOT be
calibrated (data not separably measurable / no method-independent corroborator), keeping
`signoff.calibration_status: UNCALIBRATED`. The invariant: *a model that can't be honestly calibrated
SAYS SO, on the record* -- CONSTITUTION §5 applied to the absence of evidence.

This gate is DELIBERATELY SEPARATE from `validate_calibration.py`: that gate's CALIBRATED proof-
obligation is left byte-unchanged, and the feasibility record lives at a DISTINCT filename so it never
trips the calibration gate's `consistency-note` (which keys off `calibration.yaml`). Anti-over-claim
teeth: the `verdict` enum has NO "feasible" value (an upgrade goes through `calibration.yaml`/CALIBRATED,
not a feasibility record flipping); a descriptive band must carry honesty labels and is scanned for
over-claim language; a provenance hash cannot be fabricated under a "blocked" status; a feasibility record
under a CALIBRATED signoff is a contradiction.

STRUCTURAL + ATTESTATION ONLY: a clean result means the non-feasibility claim is well-formed and bound to
the scenario's reproducible snapshot, NOT that anything is analytically valid. Composed into
`verify.py --mode release`.

Usage:
    python scripts/validate_calibration_feasibility.py                       # glob examples/*/calibration_feasibility.yaml
    python scripts/validate_calibration_feasibility.py --scenario-dir DIR    # DIR/{calibration_feasibility,signoff,run_ledger,scenario}.yaml
    python scripts/validate_calibration_feasibility.py --scenario-dir DIR --feasibility F --signoff S

Exit codes: 0 = ok (records well-formed, or none present), 1 = findings, 2 = usage / fail-closed
(a missing/unreadable scenario/ledger/signoff, or a present-but-unparseable feasibility record).
"""
from __future__ import annotations

import argparse
import re
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

# verdict has NO "FEASIBLE" value BY DESIGN -- the record structurally cannot become a back-door
# calibration claim; a channel that becomes calibratable graduates to calibration.yaml / CALIBRATED.
VERDICT_ENUM = ("NOT_FEASIBLE", "INSUFFICIENT_DATA")
# a feasibility record only makes sense under an honest no-evidence label.
ALLOWED_STATUSES = ("UNCALIBRATED", "ILLUSTRATIVE")
# the outcome-authority vocabulary (who/what produced an observed number).
SOURCE_CLASS_ENUM = ("SELF_REPORTED_BELLIGERENT", "INDEPENDENT_VISUAL", "THIRD_PARTY_ANALYTIC", "ADJUDICATED")
# a descriptive band MUST carry >= 1 of these honesty markers (else it reads as a validated forecast).
HONESTY_LABELS = {"SINGLE_SOURCE", "COMPOSITE_BUCKET", "NOT_CORROBORATED", "SELF_REPORTED", "ILLUSTRATIVE"}
# provenance hash status: a hash exists ONLY when PINNED; otherwise it must be null (no fabrication).
SHA_STATUS_ENUM = ("PINNED", "BLOCKED_FETCH_AUTH_GATED", "NOT_ATTEMPTED")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Over-claim language a descriptive band must NEVER affirmatively use (it is a plausibility check, not
# validation). The `(?<!not )` lookbehind ALLOWS the honest negated disclaimers ("not calibrated", "not
# corroborated") while still catching an affirmative "is calibrated / fully validated".
_FORBIDDEN = re.compile(r"(?<!not )\b(calibrated|validated|corroborated|confirmed|verified)\b", re.IGNORECASE)

FEASIBILITY_SPEC = {
    "required_str": ("schema_version", "id", "target", "code_version", "attempted_observable",
                     "dossier_ref", "upgrade_gap", "authority", "assessor", "feasibility_date"),
    "required_int": (),
    "enums": {"verdict": VERDICT_ENUM},
}


def _usable_doc(doc: object) -> bool:
    return isinstance(doc, dict) and bool(doc)


def _walk_strings(node: object):
    """Yield EVERY string reachable in a nested structure (scalars, list items, nested dict values).
    The over-claim scan walks this so affirmative language cannot be hidden in a band list/nested dict
    (an adversarial-verify escape). The honesty labels are scan-safe: NOT_CORROBORATED's underscore
    blocks the \\bcorroborated\\b word boundary, and the other markers contain no flagged word."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)


def _structural_problems(fdoc: dict, where: str) -> list[tuple[str, str, str]]:
    """Structure of the feasibility record: skeleton + the list/date/band/provenance checks it omits."""
    problems: list[tuple[str, str, str]] = list(_validate_skeleton(fdoc, where, FEASIBILITY_SPEC))

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    # feasibility_date: required_str catches absent; this catches a present-but-malformed value.
    fd = fdoc.get("feasibility_date")
    if _is_nonempty_str(fd) and not _valid_iso_date(fd):
        add("invalid-format", f"feasibility_date {fd!r} must be an ISO-8601 date (YYYY-MM-DD)")

    # binding_reasons: a non-empty list of non-empty strings (WHY calibration is not feasible).
    br = fdoc.get("binding_reasons")
    if br is None:
        add("missing-field", "binding_reasons is required")
    elif not isinstance(br, list) or not br or not all(_is_nonempty_str(x) for x in br):
        add("empty-reasons", "binding_reasons must be a non-empty list of non-empty strings")

    # descriptive_band (OPTIONAL): if present, it must be HONEST -- labeled + free of over-claim language.
    band = fdoc.get("descriptive_band")
    if band is not None:
        if not isinstance(band, dict):
            add("wrong-type", "descriptive_band, if present, must be a mapping")
        else:
            labels = band.get("labels")
            if not isinstance(labels, list) or not labels or not (set(labels) & HONESTY_LABELS):
                add("unlabeled-band",
                    f"descriptive_band.labels must be a non-empty list including >= 1 honesty marker "
                    f"{sorted(HONESTY_LABELS)} -- an unlabeled band reads as a validated forecast")
            sc = band.get("source_class")
            if sc is not None and sc not in SOURCE_CLASS_ENUM:
                add("invalid-enum",
                    f"descriptive_band.source_class must be one of {sorted(SOURCE_CLASS_ENUM)}; got {sc!r}")
            for text in _walk_strings(band):                  # recurse: lists + nested dicts too
                hit = _FORBIDDEN.search(text)
                if hit:
                    add("over-claim-language",
                        f"descriptive_band contains affirmative over-claim language {hit.group(0)!r} "
                        f"(in {text!r}); a band is a plausibility check, never calibrated/validated/"
                        f"corroborated -- found anywhere in the band, including nested lists/dicts")
                    break                                      # one finding suffices (single-fault)

    # provenance (OPTIONAL): a hash exists iff PINNED -- a hash under a 'blocked' status is fabrication.
    prov = fdoc.get("provenance")
    if prov is not None:
        if not isinstance(prov, list):
            add("wrong-type", "provenance, if present, must be a list of {dataset, version, sha256, sha256_status} entries")
        else:
            for i, entry in enumerate(prov):
                if not isinstance(entry, dict):
                    add("wrong-type", f"provenance[{i}] must be a mapping")
                    continue
                st, sha = entry.get("sha256_status"), entry.get("sha256")
                if st not in SHA_STATUS_ENUM:
                    add("invalid-enum", f"provenance[{i}].sha256_status must be one of {sorted(SHA_STATUS_ENUM)}; got {st!r}")
                elif st == "PINNED":
                    if not (_is_nonempty_str(sha) and _SHA256_RE.fullmatch(sha)):
                        add("invalid-format", f"provenance[{i}].sha256 must be 64 lowercase hex when PINNED; got {sha!r}")
                elif sha is not None:
                    add("provenance-contradiction",
                        f"provenance[{i}].sha256 must be null when sha256_status is {st} "
                        f"(cannot hold a hash for an un-fetched source); got {sha!r}")

    # launch_denominator_conflict (OPTIONAL): record an unreconciled denominator honestly.
    ldc = fdoc.get("launch_denominator_conflict")
    if ldc is not None and (not isinstance(ldc, dict) or ldc.get("status") not in ("UNRESOLVED", "RESOLVED")
                            or not isinstance(ldc.get("values"), list) or not ldc.get("values")):
        add("wrong-type", "launch_denominator_conflict, if present, needs status in {UNRESOLVED, RESOLVED} "
                          "and a non-empty values list")
    return problems


def _resolution_problems(fdoc: dict, ledger_cv: str, scenario_name: str,
                         where: str) -> list[tuple[str, str, str]]:
    """Scenario + ledger binding. Assumes structure passed (so fixtures stay single-fault)."""
    problems: list[tuple[str, str, str]] = []
    if fdoc["target"] != scenario_name:
        problems.append(("unresolved-scenario-ref", where,
                         f"target {fdoc['target']!r} does not name this scenario ({scenario_name!r})"))
    if fdoc["code_version"] != ledger_cv:
        problems.append(("stale-feasibility", where,
                         f"feasibility code_version {fdoc['code_version'][:12]}... != run-ledger "
                         f"{ledger_cv[:12]}...; re-assess / re-record the current snapshot"))
    return problems


def _consistency_problems(status: str, where: str) -> list[tuple[str, str, str]]:
    """A feasibility record only makes sense under an honest no-evidence label."""
    if status not in ALLOWED_STATUSES:
        return [("contradictory-status", where,
                 f"a calibration_feasibility record is present but calibration_status is {status!r}; "
                 f"a non-feasibility record cannot coexist with a CALIBRATED claim -- declare "
                 f"{' / '.join(ALLOWED_STATUSES)}")]
    return []


def _fail_closed(reason: str) -> int:
    print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
    return 2


def _report(problems: list[tuple[str, str, str]]) -> int:
    print(f"calibration-feasibility validation FAILED: {len(problems)} problem(s):", file=sys.stderr)
    for code, where, msg in problems:
        print(f"  - {code}  {where}  {msg}", file=sys.stderr)
    return 1


def _judge_one(scenario_dir: Path, feasibility_path: Path, signoff_path: Path):
    """Validate ONE feasibility record. Returns (rc, payload): rc 0/1/2; payload is an ok-message (0),
    a problems list (1), or a fail-closed reason (2)."""
    if not (scenario_dir / "scenario.yaml").is_file():
        return 2, f"{scenario_dir}/scenario.yaml is absent (no scenario to attest)"
    ldoc, lerr = load_registry(scenario_dir / "run_ledger.yaml")
    if lerr is not None or not isinstance(ldoc, dict) or not _is_nonempty_str(ldoc.get("code_version")):
        return 2, (lerr or f"{scenario_dir}/run_ledger.yaml is not a usable run-ledger (need a code_version)")
    sdoc, serr = load_registry(signoff_path)
    if serr is not None or not _usable_doc(sdoc):
        return 2, (serr or f"{signoff_path} is not a usable signoff (a feasibility record must be attested)")
    status = sdoc.get("calibration_status")
    if not _is_nonempty_str(status):
        return 2, f"{signoff_path} has no usable calibration_status"
    fdoc, ferr = load_registry(feasibility_path)
    if ferr is not None or not _usable_doc(fdoc):
        return 2, (ferr or f"{feasibility_path} is present but not a usable record (non-empty mapping)")

    where = _display(feasibility_path)
    problems = _structural_problems(fdoc, where)                       # structure first (single-fault)
    if not problems:
        problems = _resolution_problems(fdoc, ldoc["code_version"], scenario_dir.name, where)
    if not problems:
        problems = _consistency_problems(status, where)
    if problems:
        return 1, problems
    return 0, f"{where}: {fdoc['verdict']} (target {fdoc['target']})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_calibration_feasibility.py",
        description="Validate calibration-feasibility records: a well-formed, attested 'cannot calibrate' claim.",
    )
    parser.add_argument("--scenario-dir", default=None,
                        help="validate one scenario's record (default: glob examples/*/calibration_feasibility.yaml)")
    parser.add_argument("--feasibility", default=None, help="record path (default: <scenario-dir>/calibration_feasibility.yaml)")
    parser.add_argument("--signoff", default=None, help="signoff.yaml path (default: <scenario-dir>/signoff.yaml)")
    args = parser.parse_args(argv)

    if args.scenario_dir:
        scenario_dir = Path(args.scenario_dir).resolve()
        feas = Path(args.feasibility).resolve() if args.feasibility else scenario_dir / "calibration_feasibility.yaml"
        sign = Path(args.signoff).resolve() if args.signoff else scenario_dir / "signoff.yaml"
        if not feas.is_file():
            return _fail_closed(f"{feas} is absent (nothing to validate in --scenario-dir mode)")
        rc, payload = _judge_one(scenario_dir, feas, sign)
        if rc == 2:
            return _fail_closed(payload)
        if rc == 1:
            return _report(payload)
        print(f"calibration-feasibility OK ({payload})")
        return 0

    # Glob mode (CI / release): validate every committed feasibility record; none present -> vacuous pass.
    records = sorted((REPO_ROOT / "examples").glob("*/calibration_feasibility.yaml"))
    if not records:
        print("calibration-feasibility OK (no feasibility records present)")
        return 0
    all_problems: list[tuple[str, str, str]] = []
    ok = 0
    for rec in records:
        rc, payload = _judge_one(rec.parent, rec, rec.parent / "signoff.yaml")
        if rc == 2:
            return _fail_closed(payload)        # a fail-closed record taints the whole gate
        if rc == 1:
            all_problems.extend(payload)
        else:
            ok += 1
    if all_problems:
        return _report(all_problems)
    print(f"calibration-feasibility OK ({ok} record(s) validated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

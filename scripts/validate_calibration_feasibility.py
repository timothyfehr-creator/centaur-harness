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
teeth, STRUCTURE-first: the `verdict` enum has NO "feasible" value (an upgrade goes through
`calibration.yaml`/CALIBRATED, not a feasibility record flipping); UNKNOWN KEYS are rejected at every object
level (a smuggled `matches_ground_truth`/comparison field cannot ride along); an optional `external_context`
band must carry machine-readable honesty enums (`comparison_role: CONTEXT_ONLY`, `calibration_effect: NONE`,
`comparability_to_model_p`) + a ranged observed band + >= 1 honesty label, so it can never read as a
validated forecast; a clause-aware over-claim word scan over the WHOLE record is defense-in-depth on top
(honest negated disclaimers pass); a provenance hash cannot be fabricated under a "blocked" status; a
feasibility record under a CALIBRATED signoff is a contradiction.

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
# an external-context block MUST carry >= 1 of these honesty markers (else it reads as a validated forecast).
HONESTY_LABELS = {"SINGLE_SOURCE", "COMPOSITE_BUCKET", "NOT_CORROBORATED", "SELF_REPORTED", "ILLUSTRATIVE"}
# the machine-readable honesty fields a context block MUST carry, each pinned to its ONLY honest value:
# the block can never be a calibration input (CONTEXT_ONLY) and never moves a parameter (NONE). These are
# the STRUCTURAL boundary -- the over-claim word scan is only defense-in-depth on top of them.
COMPARISON_ROLE_ENUM = ("CONTEXT_ONLY",)            # the sole legal value -- never an input to calibration
CALIBRATION_EFFECT_ENUM = ("NONE",)                 # the sole legal value -- the block moves no parameter
COMPARABILITY_ENUM = ("NONE", "INDIRECT", "DIRECT")  # how comparable the observed band is to the model's p
COVERAGE_ENUM = ("PARTIAL", "FULL")
# provenance hash status: a hash exists ONLY when PINNED; otherwise it must be null (no fabrication).
SHA_STATUS_ENUM = ("PINNED", "BLOCKED_FETCH_AUTH_GATED", "NOT_ATTEMPTED")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Unknown-key allow-lists: rejecting extra keys at EVERY object level is the real boundary -- it kills the
# `matches_ground_truth: true` / smuggled-comparison-field bypasses a word scan can never enumerate.
ALLOWED_TOP = {"schema_version", "id", "target", "code_version", "verdict", "attempted_observable",
               "binding_reasons", "dossier_ref", "upgrade_gap", "authority", "assessor", "feasibility_date",
               "external_context", "provenance", "launch_denominator_conflict"}
ALLOWED_CONTEXT = {"observed_range_pct", "coverage", "weeks_computed", "weeks_in_window",
                   "comparability_to_model_p", "comparison_role", "calibration_effect",
                   "labels", "source_class", "caveat"}
ALLOWED_PROV_ENTRY = {"dataset", "version", "sha256", "sha256_status", "url", "snapshot_date"}
ALLOWED_LDC = {"status", "values", "note"}
ALLOWED_LDC_VALUE = {"month", "launched", "source"}

# Affirmative over-claim words a record must never AFFIRM (it is a plausibility check, not validation).
_OVERCLAIM_WORD = re.compile(r"\b(calibrated|validated|corroborated|confirmed|verified)\b", re.IGNORECASE)
# a negator EARLIER IN THE SAME CLAUSE exempts the word (the honest "not corroborated" / "never validated").
_NEGATOR = re.compile(r"\b(not|never|no|none|cannot|without)\b|n't", re.IGNORECASE)
# clause boundaries: sentence/clause punctuation + contrastive conjunctions, so "not calibrated BUT validated"
# still fails on the second clause (clause-aware, not a single global lookbehind).
_CLAUSE_SPLIT = re.compile(r"[.;,:]|\b(?:but|however|though|although|yet|while|whereas)\b", re.IGNORECASE)

FEASIBILITY_SPEC = {
    "required_str": ("schema_version", "id", "target", "code_version", "attempted_observable",
                     "dossier_ref", "upgrade_gap", "authority", "assessor", "feasibility_date"),
    "required_int": (),
    "enums": {"verdict": VERDICT_ENUM},
}


def _overclaim_hit(text: str) -> str | None:
    """The first AFFIRMATIVE over-claim word in `text`, or None. Clause-aware: a negator earlier in the same
    clause exempts the word -- so "not independently corroborated" / "never validated" PASS while "is
    calibrated" / "fully validated" FAIL. Splitting on clause boundaries (incl. contrastive conjunctions)
    means "not calibrated but validated" still FAILS on the second clause."""
    for clause in _CLAUSE_SPLIT.split(text):
        m = _OVERCLAIM_WORD.search(clause)
        if m and not _NEGATOR.search(clause[:m.start()]):
            return m.group(0)
    return None


def _reject_unknown(obj: dict, allowed: set[str], where: str, prefix: str,
                    add) -> None:
    """Append an `unknown-key` finding for any key outside `allowed`. Rejecting extra keys at every object
    level is the structural boundary (a smuggled `matches_ground_truth`/comparison field cannot hide)."""
    for k in obj:
        if k not in allowed:
            add("unknown-key", f"{prefix}{k!r} is not an allowed key (allowed: {sorted(allowed)}) -- a "
                               f"feasibility record cannot smuggle an un-vetted field past the gate")


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


def _context_problems(ctx: dict, where: str, add) -> None:
    """external_context (OPTIONAL): a labeled, machine-readable plausibility band that can NEVER read as a
    validated forecast. When present it must carry the honesty enums (each pinned to its sole honest value),
    ranged numerics, and >= 1 honesty label -- so the block structurally cannot be a calibration input."""
    _reject_unknown(ctx, ALLOWED_CONTEXT, where, "external_context.", add)
    # the machine-readable honesty enums -- the STRUCTURAL boundary (comparison_role/calibration_effect each
    # have one sole legal value, so the block can never affirm it is a calibration input or moves a param).
    for field, enum in (("comparison_role", COMPARISON_ROLE_ENUM),
                        ("calibration_effect", CALIBRATION_EFFECT_ENUM),
                        ("comparability_to_model_p", COMPARABILITY_ENUM),
                        ("coverage", COVERAGE_ENUM),
                        ("source_class", SOURCE_CLASS_ENUM)):
        val = ctx.get(field)
        if val is None:
            add("missing-field", f"external_context.{field} is required (a machine-readable honesty field)")
        elif val not in enum:
            add("invalid-enum", f"external_context.{field} must be one of {sorted(enum)}; got {val!r}")
    if not _is_nonempty_str(ctx.get("caveat")):
        add("missing-field", "external_context.caveat is required (a non-empty disclaimer string)")
    labels = ctx.get("labels")
    if not isinstance(labels, list) or not labels or not (set(labels) & HONESTY_LABELS):
        add("unlabeled-band",
            f"external_context.labels must be a non-empty list including >= 1 honesty marker "
            f"{sorted(HONESTY_LABELS)} -- an unlabeled context block reads as a validated forecast")
    rng = ctx.get("observed_range_pct")
    if not (isinstance(rng, list) and len(rng) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in rng)):
        add("missing-field", "external_context.observed_range_pct must be a [low, high] pair of numbers")
    elif not (0 <= rng[0] <= rng[1] <= 100):
        add("out-of-range", f"external_context.observed_range_pct {rng} must satisfy 0 <= low <= high <= 100")
    wc, ww = ctx.get("weeks_computed"), ctx.get("weeks_in_window")
    if not (isinstance(wc, int) and not isinstance(wc, bool)
            and isinstance(ww, int) and not isinstance(ww, bool)):
        add("missing-field", "external_context.weeks_computed and weeks_in_window must both be integers")
    elif not (1 <= wc <= ww):
        add("out-of-range",
            f"external_context weeks_computed {wc} must satisfy 1 <= weeks_computed <= weeks_in_window {ww}")


def _structural_problems(fdoc: dict, where: str) -> list[tuple[str, str, str]]:
    """Structure of the feasibility record: skeleton + unknown-key rejection at every object level + the
    list/date/context/provenance checks the skeleton omits + a whole-doc over-claim scan."""
    problems: list[tuple[str, str, str]] = list(_validate_skeleton(fdoc, where, FEASIBILITY_SPEC))

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    # unknown-key at the top level -- the structural boundary (a smuggled comparison/ground-truth field
    # cannot ride along in a record the gate "doesn't look at").
    _reject_unknown(fdoc, ALLOWED_TOP, where, "", add)

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

    # external_context (OPTIONAL): if present, it must be HONEST -- labeled, ranged, machine-readable.
    ctx = fdoc.get("external_context")
    if ctx is not None:
        if not isinstance(ctx, dict):
            add("wrong-type", "external_context, if present, must be a mapping")
        else:
            _context_problems(ctx, where, add)

    # provenance (OPTIONAL): a hash exists iff PINNED -- a hash under a 'blocked' status is fabrication.
    prov = fdoc.get("provenance")
    if prov is not None:
        if not isinstance(prov, list):
            add("wrong-type", "provenance, if present, must be a list of "
                              "{dataset, version, sha256, sha256_status, url?, snapshot_date?} entries")
        else:
            for i, entry in enumerate(prov):
                if not isinstance(entry, dict):
                    add("wrong-type", f"provenance[{i}] must be a mapping")
                    continue
                _reject_unknown(entry, ALLOWED_PROV_ENTRY, where, f"provenance[{i}].", add)
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
    if ldc is not None:
        if (not isinstance(ldc, dict) or ldc.get("status") not in ("UNRESOLVED", "RESOLVED")
                or not isinstance(ldc.get("values"), list) or not ldc.get("values")):
            add("wrong-type", "launch_denominator_conflict, if present, needs status in {UNRESOLVED, RESOLVED} "
                              "and a non-empty values list")
        else:
            _reject_unknown(ldc, ALLOWED_LDC, where, "launch_denominator_conflict.", add)
            for i, v in enumerate(ldc["values"]):
                if isinstance(v, dict):
                    _reject_unknown(v, ALLOWED_LDC_VALUE, where, f"launch_denominator_conflict.values[{i}].", add)

    # Over-claim scan (defense-in-depth ON TOP of the structural honesty enums): NO affirmative
    # calibrated/validated/corroborated/confirmed/verified anywhere in the record (clause-aware -- honest
    # negated disclaimers pass). The machine-readable enums are the boundary; this catches an affirmation
    # slipped into an allowed free-text field (a caveat, a binding reason, a note).
    for text in _walk_strings(fdoc):
        hit = _overclaim_hit(text)
        if hit:
            add("over-claim-language",
                f"affirmative over-claim word {hit!r} in {text!r}; a feasibility record is a plausibility "
                f"check, never calibrated/validated/corroborated/confirmed/verified")
            break                                              # one finding suffices (single-fault)
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

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
import unicodedata
from pathlib import Path

from validate_schemas import (
    REPO_ROOT,
    _display,
    _is_nonempty_str,
    _valid_iso_date,
    _validate_skeleton,
)
from validate_claims import load_registry
from validate_run_ledger import _sha256

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
# how comparable the observed band is to the model's p. NO `DIRECT`: a directly-comparable band IS the model's
# quantity -- that would be a calibration target, which contradicts a feasibility record + comparison_role:
# CONTEXT_ONLY. A feasibility record's band is at most INDIRECTLY related.
COMPARABILITY_ENUM = ("NONE", "INDIRECT")
COVERAGE_ENUM = ("PARTIAL", "FULL")
# provenance hash status: a hash exists ONLY when PINNED; otherwise it must be null (no fabrication).
SHA_STATUS_ENUM = ("PINNED", "BLOCKED_FETCH_AUTH_GATED", "NOT_ATTEMPTED")
# the dossier lives OUTSIDE the repo (centaur_engine_planning/) -- its hash is recorded honestly as
# EXTERNAL_NOT_PINNED (#7-min), never fabricated; an in-repo copy + full manifest are deferred.
DOSSIER_SHA_STATUS_ENUM = ("PINNED", "EXTERNAL_NOT_PINNED", "NOT_ATTEMPTED")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# feasibility-verdict dispositions oblige a bound record; the others must NOT carry one.
_FEASIBILITY_DISPOSITIONS = ("NOT_FEASIBLE", "INSUFFICIENT_DATA")

# Unknown-key allow-lists: rejecting extra keys at EVERY object level is the real boundary -- it kills the
# `matches_ground_truth: true` / smuggled-comparison-field bypasses a word scan can never enumerate.
ALLOWED_TOP = {"schema_version", "id", "target", "code_version", "verdict", "attempted_observable",
               "binding_reasons", "dossier_ref", "dossier_sha256", "dossier_sha256_status",
               "upgrade_gap", "authority", "assessor", "feasibility_date",
               "external_context", "provenance", "launch_denominator_conflict"}
ALLOWED_CONTEXT = {"observed_range_pct", "coverage", "weeks_computed", "weeks_in_window",
                   "comparability_to_model_p", "comparison_role", "calibration_effect",
                   "labels", "source_class", "caveat"}
ALLOWED_PROV_ENTRY = {"dataset", "version", "sha256", "sha256_status", "url", "snapshot_date"}
ALLOWED_LDC = {"status", "values", "note"}
ALLOWED_LDC_VALUE = {"month", "launched", "source"}
# The keys at each level that LEGITIMATELY carry a nested object/list. Every OTHER allowed key must hold a
# scalar -- so a smuggled comparison cannot ride along inside an allowed scalar key (the adversarial-verify
# escape: `note: {matches_ground_truth: true}`). Unknown-KEY rejection alone is not the boundary; key+shape is.
CONTAINER_TOP = {"binding_reasons", "external_context", "provenance", "launch_denominator_conflict"}
CONTAINER_CONTEXT = {"observed_range_pct", "labels"}
CONTAINER_LDC = {"values"}
_SCALAR = (str, int, float, bool, type(None))

# Affirmative over-claim words a record must never AFFIRM. NOTE: this scan is DEFENSE-IN-DEPTH, not the
# boundary -- a denylist of words can never be complete (synonyms, morphology). The STRUCTURAL boundary is
# unknown-key + scalar-only + the pinned honesty enums; this just catches an affirmation in plain prose.
_OVERCLAIM_WORD = re.compile(r"\b(calibrated|validated|corroborated|confirmed|verified)\b", re.IGNORECASE)
_NEG_WORDS = {"not", "never", "no", "none", "cannot", "without"}
# clause boundaries: sentence/clause punctuation + contrastive conjunctions, so "not calibrated BUT validated"
# still fails on the second clause (clause-aware, not a single global lookbehind).
_CLAUSE_SPLIT = re.compile(r"[.;,:]|\b(?:but|however|though|although|yet|while|whereas)\b", re.IGNORECASE)


def _reject_nonscalar(obj: dict, container_keys: set[str], where: str, prefix: str, add) -> None:
    """Append a `non-scalar-value` finding for any allowed key OUTSIDE `container_keys` whose value is a
    dict/list. Closes the smuggle vector where an allowed SCALAR key (`note`, `source`, `version`, ...)
    carries a nested object the unknown-key check never recurses into."""
    for k, v in obj.items():
        if k not in container_keys and not isinstance(v, _SCALAR):
            add("non-scalar-value", f"{prefix}{k!r} must be a scalar (got {type(v).__name__}) -- an allowed "
                                    f"scalar key cannot carry a nested object/list smuggling an un-vetted field")

FEASIBILITY_SPEC = {
    "required_str": ("schema_version", "id", "target", "code_version", "attempted_observable",
                     "dossier_ref", "upgrade_gap", "authority", "assessor", "feasibility_date"),
    "required_int": (),
    "enums": {"verdict": VERDICT_ENUM},
}


def _overclaim_hit(text: str) -> str | None:
    """The first AFFIRMATIVE over-claim word in `text`, or None. NFKC-normalized (folds full-width /
    compatibility spellings; cross-script homoglyphs remain a known residual -- this scan is defense-in-depth,
    not the boundary). A negator within the FEW WORDS IMMEDIATELY preceding the flagged word exempts it -- so "not independently
    corroborated" / "never validated" PASS, while "no question that the model was validated" FAILS (the
    leading negator is too far to govern the affirmation -- the earlier-fix fail-open). Clause splitting
    (incl. contrastive conjunctions) keeps "not calibrated but validated" failing on the second clause."""
    for clause in _CLAUSE_SPLIT.split(unicodedata.normalize("NFKC", text)):
        m = _OVERCLAIM_WORD.search(clause)
        if not m:
            continue
        preceding = re.findall(r"[a-z']+", clause[: m.start()].lower())[-4:]  # the 4 words before the hit
        if any(w in _NEG_WORDS or w.endswith("n't") for w in preceding):
            continue
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
    _reject_nonscalar(ctx, CONTAINER_CONTEXT, where, "external_context.", add)
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
    # a non-empty list whose items are ALL strings (the all-str guard both rejects a dict/list item smuggling
    # along AND keeps the set() below crash-safe -- an unhashable item would otherwise raise) with >= 1 marker.
    if (not isinstance(labels, list) or not labels or not all(isinstance(x, str) for x in labels)
            or not (set(labels) & HONESTY_LABELS)):
        add("unlabeled-band",
            f"external_context.labels must be a non-empty list of strings including >= 1 honesty marker "
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

    # unknown-key + scalar-only at the top level -- the structural boundary (a smuggled comparison/ground-truth
    # field cannot ride along, neither as an extra key NOR inside an allowed scalar key's value).
    _reject_unknown(fdoc, ALLOWED_TOP, where, "", add)
    _reject_nonscalar(fdoc, CONTAINER_TOP, where, "", add)

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
                _reject_nonscalar(entry, set(), where, f"provenance[{i}].", add)  # every prov field is scalar
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

    # dossier binding (#7-min, OPTIONAL): the dossier is EXTERNAL (centaur_engine_planning/), so its hash is
    # recorded as EXTERNAL_NOT_PINNED -- a hash exists iff PINNED, never fabricated for an un-pinned source.
    dstatus, dsha = fdoc.get("dossier_sha256_status"), fdoc.get("dossier_sha256")
    if dstatus is not None or dsha is not None:
        if dstatus not in DOSSIER_SHA_STATUS_ENUM:
            add("invalid-enum", f"dossier_sha256_status must be one of {sorted(DOSSIER_SHA_STATUS_ENUM)}; got {dstatus!r}")
        elif dstatus == "PINNED":
            if not (_is_nonempty_str(dsha) and _SHA256_RE.fullmatch(dsha)):
                add("invalid-format", f"dossier_sha256 must be 64 lowercase hex when dossier_sha256_status is PINNED; got {dsha!r}")
        elif dsha is not None:
            add("dossier-contradiction",
                f"dossier_sha256 must be null when dossier_sha256_status is {dstatus} "
                f"(an external/un-pinned dossier carries no in-repo hash); got {dsha!r}")

    # launch_denominator_conflict (OPTIONAL): record an unreconciled denominator honestly.
    ldc = fdoc.get("launch_denominator_conflict")
    if ldc is not None:
        if (not isinstance(ldc, dict) or ldc.get("status") not in ("UNRESOLVED", "RESOLVED")
                or not isinstance(ldc.get("values"), list) or not ldc.get("values")):
            add("wrong-type", "launch_denominator_conflict, if present, needs status in {UNRESOLVED, RESOLVED} "
                              "and a non-empty values list")
        else:
            _reject_unknown(ldc, ALLOWED_LDC, where, "launch_denominator_conflict.", add)
            _reject_nonscalar(ldc, CONTAINER_LDC, where, "launch_denominator_conflict.", add)  # note/status scalar
            for i, v in enumerate(ldc["values"]):
                if isinstance(v, dict):
                    _reject_unknown(v, ALLOWED_LDC_VALUE, where, f"launch_denominator_conflict.values[{i}].", add)
                    _reject_nonscalar(v, set(), where, f"launch_denominator_conflict.values[{i}].", add)

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


def _binding_problems(disp: object, record_exists: bool, feasibility_path: Path, fdoc: dict | None,
                      ref: object, sha_decl: object, where: str) -> list[tuple[str, str, str]]:
    """Disposition <-> record binding (#2). The signoff DECLARES the disposition; this enforces that a
    feasibility verdict is backed by a record whose verdict/id/bytes match what was signed -- so deleting or
    silently editing the record fails release. Assumes any present record already passed structure."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if disp in _FEASIBILITY_DISPOSITIONS:
        if not record_exists:
            add("missing-feasibility-record",
                f"signoff calibration_disposition is {disp} but no calibration_feasibility.yaml exists -- "
                f"the disposition must be backed by a record (it cannot just 'say so')")
            return problems
        if fdoc.get("verdict") != disp:
            add("disposition-mismatch",
                f"record verdict {fdoc.get('verdict')!r} != signoff calibration_disposition {disp!r}")
        if fdoc.get("id") != ref:
            add("unresolved-feasibility-ref",
                f"record id {fdoc.get('id')!r} != signoff calibration_feasibility_ref {ref!r}")
        actual = _sha256(feasibility_path)
        if actual != sha_decl:
            add("stale-feasibility-binding",
                f"sha256(record) {actual[:12]}... != signoff calibration_feasibility_sha256 "
                f"{(sha_decl if _is_nonempty_str(sha_decl) else '<absent>')[:12]}...; "
                f"re-sign (update calibration_feasibility_sha256) after editing the record")
    elif disp in ("NONE", "CALIBRATED") and record_exists:
        add("disposition-mismatch",
            f"a calibration_feasibility.yaml is present but signoff calibration_disposition is {disp} "
            f"(a record obliges a feasibility verdict -- NOT_FEASIBLE / INSUFFICIENT_DATA)")
    return problems


def _judge_one(scenario_dir: Path, feasibility_path: Path, signoff_path: Path, *, bind: bool):
    """Judge ONE scenario. Returns (rc, payload): rc 0/1/2; payload is an ok-message (0), a problems list
    (1), or a fail-closed reason (2). When `bind`, the signoff's calibration_disposition drives a
    bidirectional record binding (a feasibility verdict obliges a matching, hash-bound record); when not
    (an explicit --feasibility override), only the record's own well-formedness is checked."""
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

    where = _display(feasibility_path)
    record_exists = feasibility_path.is_file()
    fdoc: dict | None = None
    problems: list[tuple[str, str, str]] = []
    if record_exists:
        fdoc, ferr = load_registry(feasibility_path)
        if ferr is not None or not _usable_doc(fdoc):
            return 2, (ferr or f"{feasibility_path} is present but not a usable record (non-empty mapping)")
        problems = _structural_problems(fdoc, where)                   # structure first (single-fault)
        if not problems:
            problems = _resolution_problems(fdoc, ldoc["code_version"], scenario_dir.name, where)
        if not problems:
            problems = _consistency_problems(status, where)

    if bind and not problems:        # don't pile binding findings onto a structurally-broken record
        problems = _binding_problems(sdoc.get("calibration_disposition"), record_exists, feasibility_path,
                                     fdoc, sdoc.get("calibration_feasibility_ref"),
                                     sdoc.get("calibration_feasibility_sha256"),
                                     where if record_exists else _display(signoff_path))
    if problems:
        return 1, problems
    if not record_exists:
        return 0, f"{scenario_dir.name}: disposition {sdoc.get('calibration_disposition')!r}, no record required"
    return 0, f"{where}: {fdoc['verdict']} (target {fdoc['target']})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_calibration_feasibility.py",
        description="Validate calibration-feasibility records: a well-formed, attested 'cannot calibrate' claim.",
    )
    parser.add_argument("--scenario-dir", default=None,
                        help="validate one scenario (default: sweep examples/*/ driven by each signoff's disposition)")
    parser.add_argument("--feasibility", default=None,
                        help="record path override (default: <scenario-dir>/calibration_feasibility.yaml). "
                             "Passing it validates that record's SHAPE only -- no disposition binding.")
    parser.add_argument("--signoff", default=None, help="signoff.yaml path (default: <scenario-dir>/signoff.yaml)")
    args = parser.parse_args(argv)

    if args.scenario_dir:
        scenario_dir = Path(args.scenario_dir).resolve()
        sign = Path(args.signoff).resolve() if args.signoff else scenario_dir / "signoff.yaml"
        if args.feasibility:                  # explicit record override => shape-only, must exist
            feas = Path(args.feasibility).resolve()
            if not feas.is_file():
                return _fail_closed(f"{feas} is absent (nothing to validate with an explicit --feasibility)")
            rc, payload = _judge_one(scenario_dir, feas, sign, bind=False)
        else:                                 # default => disposition-driven binding (record may be absent)
            feas = scenario_dir / "calibration_feasibility.yaml"
            rc, payload = _judge_one(scenario_dir, feas, sign, bind=True)
        if rc == 2:
            return _fail_closed(payload)
        if rc == 1:
            return _report(payload)
        print(f"calibration-feasibility OK ({payload})")
        return 0

    # Sweep mode (CI / release): every example scenario, driven by its signoff disposition (so a NOT_FEASIBLE
    # signoff with a deleted record FAILS, not vacuously passes). dir set = signoff-bearing OR record-bearing.
    examples = REPO_ROOT / "examples"
    dirs = sorted({p.parent for p in examples.glob("*/signoff.yaml")}
                  | {p.parent for p in examples.glob("*/calibration_feasibility.yaml")})
    if not dirs:
        print("calibration-feasibility OK (no attested scenarios present)")
        return 0
    all_problems: list[tuple[str, str, str]] = []
    records = 0
    for d in dirs:
        rc, payload = _judge_one(d, d / "calibration_feasibility.yaml", d / "signoff.yaml", bind=True)
        if rc == 2:
            return _fail_closed(payload)        # a fail-closed scenario taints the whole gate
        if rc == 1:
            all_problems.extend(payload)
        elif (d / "calibration_feasibility.yaml").is_file():
            records += 1
    if all_problems:
        return _report(all_problems)
    print(f"calibration-feasibility OK ({len(dirs)} scenario(s) checked, {records} record(s) validated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

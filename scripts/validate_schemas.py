#!/usr/bin/env python3
"""Centaur schema validator.

Structural validation only -- it checks the SHAPE of a document, not whether its
claims are source-backed (sourcing is WP2.x). Uses PyYAML's ``safe_load`` plus
hand-rolled rules. The default kind is ``scenario`` (rich cross-field rules); the
other kinds (agent / source / claim / event / turn) are flat declarative skeletons.

Usage:
    python scripts/validate_schemas.py                    # validate examples/**/scenario.yaml
    python scripts/validate_schemas.py PATH ...           # validate given files / dirs (scenario)
    python scripts/validate_schemas.py --kind source PATH # validate as a different kind

Exit codes: 0 = all valid, 1 = validation failure(s), 2 = usage / nothing-to-validate.

Fail-closed: a default (no-args) scan, or a directory scan, that discovers ZERO
files of the chosen kind exits 2 -- a gate that validated nothing must not report
success.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml  # only third-party dependency; safe_load only

REPO_ROOT = Path(__file__).resolve().parent.parent
PROB_SUM_TOLERANCE = 0.05  # loose on purpose; tightening is backlog


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _nonempty_items(items: object) -> list:
    """Items that count: a non-empty string, or a mapping with a non-empty
    ``description``. (Richer per-signpost fields are accepted but not required.)"""
    out: list = []
    if not isinstance(items, list):
        return out
    for it in items:
        if _is_nonempty_str(it):
            out.append(it)
        elif isinstance(it, dict) and _is_nonempty_str(it.get("description")):
            out.append(it)
    return out


def validate_doc(doc: object, where: str) -> list[tuple[str, str, str]]:
    """Validate a parsed scenario document. Returns a list of (code, where, message)."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not isinstance(doc, dict):
        add("yaml-parse-error", "top-level YAML must be a mapping")
        return problems

    if not _is_nonempty_str(doc.get("schema_version")):
        add("missing-schema-version",
            "schema_version is required and must be a non-empty string")

    # World-vs-game label (CONSTITUTION §4, WP3.2). Required + constrained to the shared
    # WORLD_VS_GAME_LABELS vocab that validate_state.py enforces on state items. Checked
    # above the branches early-return so the label fault is independent of branch shape.
    label = doc.get("label")
    if not _is_nonempty_str(label):
        add("missing-field", "label is required and must be a non-empty string")
    elif label not in WORLD_VS_GAME_LABELS:
        add("invalid-enum",
            f"label must be one of {sorted(WORLD_VS_GAME_LABELS)}; got {label!r}")

    branches = doc.get("branches")
    if not isinstance(branches, list) or len(branches) < 2:
        add("missing-branches", "branches must be a list of at least 2 items")
        return problems  # cannot run per-branch / sum rules meaningfully

    total = 0.0
    sum_ok = True
    for i, branch in enumerate(branches):
        tag = f"branch[{i}]"
        if not isinstance(branch, dict):
            add("probability-not-numeric", f"{tag} must be a mapping")
            sum_ok = False
            continue

        prob = branch.get("probability")
        # bool is a subclass of int, so reject it explicitly.
        if isinstance(prob, bool) or not isinstance(prob, (int, float)):
            add("probability-not-numeric", f"{tag} probability must be a number; got {prob!r}")
            sum_ok = False
        elif not (0.0 <= prob <= 1.0):
            add("probability-out-of-range", f"{tag} probability {prob} is not in [0, 1]")
            sum_ok = False
        else:
            total += float(prob)

        if len(_nonempty_items(branch.get("signposts"))) < 3:
            add("too-few-signposts", f"{tag} requires at least 3 non-empty signposts")
        if len(_nonempty_items(branch.get("falsifiers"))) < 1:
            add("missing-falsifier", f"{tag} requires at least 1 non-empty falsifier")

        if not _is_nonempty_str(branch.get("rationale")) and not _is_nonempty_str(
            branch.get("update_mechanism")
        ):
            add("missing-rationale-or-update",
                f"{tag} must have a non-empty rationale or update_mechanism")

    # +1e-9 absorbs floating-point summation error so the ±tolerance boundary is
    # inclusive (e.g. 0.55 + 0.50 == 1.0500000000000044 still passes at tol 0.05).
    if sum_ok and abs(total - 1.0) > PROB_SUM_TOLERANCE + 1e-9:
        add("probability-sum-out-of-range",
            f"branch probabilities sum to {total:.3f}; must be within "
            f"{PROB_SUM_TOLERANCE} of 1.0 (no implicit residual -- add an explicit branch)")

    return problems


# --- Skeleton kinds (WP1.2) ------------------------------------------------------
# Flat, declarative skeletons for the non-scenario document kinds: required
# non-empty-string fields, required integer fields, and enum fields. STRUCTURAL only
# -- no cross-refs or semantics (those are WP2.x / WP5). Enum values are PROVISIONAL
# "label vocabularies" grounded in established frameworks (semantics deferred):
# agent.type (IR actor typology), source.tier (NATO STANAG 2511 / OSINT),
# claim.confidence (intel evidential status; the tier rule in validate_claims.py
# triggers on the top value, CONFIRMED), event.category (DIME), event.confidence
# (reuses the claim evidential-status vocabulary; event->claim resolution lives in
# validate_events.py).
# Keep each SPEC in sync with its schemas/<kind>.schema.md contract -- nothing tests
# that the human-readable prose matches these dicts.
AGENT_SPEC = {
    "required_str": ("schema_version", "id", "name"),
    "required_int": (),
    "enums": {"type": ("STATE", "INSTITUTION", "NON_STATE")},
}
SOURCE_SPEC = {
    "required_str": ("schema_version", "id", "title"),
    "required_int": (),
    "enums": {"tier": ("OFFICIAL", "MAINSTREAM", "SOCIAL")},
}
CLAIM_SPEC = {
    "required_str": ("schema_version", "id", "text"),
    "required_int": (),
    "enums": {"confidence": ("CONFIRMED", "LIKELY", "UNCERTAIN", "UNASSESSED")},
}
EVENT_SPEC = {
    "required_str": ("schema_version", "id", "description"),
    "required_int": (),
    "enums": {
        "category": ("DIPLOMATIC", "INFORMATION", "MILITARY", "ECONOMIC"),
        "confidence": ("CONFIRMED", "LIKELY", "UNCERTAIN", "UNASSESSED"),
    },
}
TURN_SPEC = {
    "required_str": ("schema_version", "id"),
    "required_int": ("number",),  # type only; ordering/replay semantics are WP7
    "enums": {},
}

# CONSTITUTION §4 world-vs-game labels. Reused by validate_state.py (WP2.3, the
# source-or-label gate) and the output-label gate (WP3.2). REAL_WORLD_BASELINE is the
# only label that asserts an external real-world fact (so it must be claim-backed).
# State is registry-only, so this is a shared constant rather than a SCHEMA_REGISTRY kind.
WORLD_VS_GAME_LABELS = (
    "REAL_WORLD_BASELINE", "ASSUMPTION", "MODEL_OUTPUT",
    "GAMED_FUTURE", "ANALYST_JUDGMENT", "ILLUSTRATIVE",
)


def _validate_skeleton(doc: object, where: str, spec: dict) -> list[tuple[str, str, str]]:
    """Validate a flat skeleton document against a spec. Structural only."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not isinstance(doc, dict):
        add("yaml-parse-error", "top-level YAML must be a mapping")
        return problems

    for field in spec["required_str"]:
        if not _is_nonempty_str(doc.get(field)):
            if field == "schema_version":
                add("missing-schema-version",
                    "schema_version is required and must be a non-empty string")
            else:
                add("missing-field", f"{field} is required and must be a non-empty string")

    for field in spec["required_int"]:
        value = doc.get(field)
        if value is None:
            add("missing-field", f"{field} is required")
        elif isinstance(value, bool) or not isinstance(value, int):
            # bool is a subclass of int, so reject it explicitly.
            add("wrong-type", f"{field} must be an integer; got {type(value).__name__}")

    # An absent enum field is "missing-field" (not "invalid-enum"); only a present,
    # out-of-set value is "invalid-enum".
    for field, allowed in spec["enums"].items():
        value = doc.get(field)
        if not _is_nonempty_str(value):
            add("missing-field", f"{field} is required and must be a non-empty string")
        elif value not in allowed:
            add("invalid-enum", f"{field} must be one of {sorted(allowed)}; got {value!r}")

    return problems


# kind -> (canonical filename, skeleton spec or None, custom validator or None)
SCHEMA_REGISTRY: dict[str, tuple] = {
    "scenario": ("scenario.yaml", None, validate_doc),
    "agent": ("agents.yaml", AGENT_SPEC, None),
    "source": ("sources.yaml", SOURCE_SPEC, None),
    "claim": ("claims.yaml", CLAIM_SPEC, None),
    "event": ("events.yaml", EVENT_SPEC, None),
    "turn": ("turns.yaml", TURN_SPEC, None),
}
FILENAME_TO_KIND = {fname: kind for kind, (fname, _s, _c) in SCHEMA_REGISTRY.items()}


def validate_kind(doc: object, where: str, kind: str) -> list[tuple[str, str, str]]:
    """Dispatch validation to the given kind's validator (custom or skeleton)."""
    _fname, spec, custom = SCHEMA_REGISTRY[kind]
    if custom is not None:
        return custom(doc, where)
    return _validate_skeleton(doc, where, spec)


def _display(path: Path) -> str:
    for base in (Path.cwd(), REPO_ROOT):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def validate_file(path: Path, kind: str | None = None) -> list[tuple[str, str, str]]:
    """Parse and validate a single document.

    ``kind`` defaults to inference from the filename (falling back to scenario), so
    verify.py's ``validate_file(path)`` call stays scenario-compatible. Reused by
    verify.py's scaffold hook.
    """
    if kind is None:
        kind = FILENAME_TO_KIND.get(path.name, "scenario")
    where = _display(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [("yaml-parse-error", where, f"cannot read file: {exc}")]
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [("yaml-parse-error", where, f"YAML parse error: {exc}")]
    return validate_kind(doc, where, kind)


def _discover(paths: list[str], missing: list[str], kind: str = "scenario") -> list[Path] | None:
    """Resolve files to validate for ``kind``.

    - No paths: glob REPO_ROOT/examples/**/<canonical>. Zero found -> None.
    - A directory arg: glob <canonical> beneath it. Zero found -> None.
    - A file arg: that file.
    Returns the file list, or None to signal a fail-closed "nothing to validate".
    """
    canonical = SCHEMA_REGISTRY[kind][0]
    if not paths:
        found = sorted(REPO_ROOT.glob(f"examples/**/{canonical}"))
        return found or None

    files: list[Path] = []
    saw_empty_dir = False
    for p in paths:
        pp = Path(p)
        pp = pp if pp.is_absolute() else (Path.cwd() / pp)
        if pp.is_dir():
            sub = sorted(pp.glob(f"**/{canonical}"))
            if not sub:
                saw_empty_dir = True
            files.extend(sub)
        elif pp.is_file():
            files.append(pp)
        else:
            missing.append(p)
    if saw_empty_dir and not files:
        return None
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_schemas.py",
        description="Validate Centaur YAML documents (structural; no source resolution).",
    )
    parser.add_argument(
        "--kind",
        choices=sorted(SCHEMA_REGISTRY),
        default="scenario",
        help="document kind to validate (default: scenario)",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="files, or dirs to search for the kind's canonical file "
             "(default: examples/**/<kind>.yaml)",
    )
    args = parser.parse_args(argv)
    kind = args.kind

    missing: list[str] = []
    files = _discover(args.paths, missing, kind)
    if missing:
        for p in missing:
            print(f"error: path not found: {p}", file=sys.stderr)
        return 2
    if files is None:
        canonical = SCHEMA_REGISTRY[kind][0]
        target = " ".join(args.paths) if args.paths else f"examples/**/{canonical}"
        print(
            f"error: no {kind} files found ({target}); refusing to report clean.",
            file=sys.stderr,
        )
        return 2

    findings: list[tuple[str, str, str]] = []
    for path in files:
        findings.extend(validate_file(path, kind))

    if findings:
        print(f"schema validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"schema validation OK ({len(files)} {kind} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

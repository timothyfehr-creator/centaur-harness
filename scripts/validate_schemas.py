#!/usr/bin/env python3
"""Centaur scenario-schema validator.

Structural validation only -- it checks the SHAPE of a scenario file, not whether
its claims are source-backed (sourcing is WP2.3). Uses PyYAML's ``safe_load`` plus
hand-rolled cross-field rules (probability sum, signpost/falsifier counts, and the
rationale-or-update rule), which a declarative schema engine cannot express alone.

Usage:
    python scripts/validate_schemas.py            # validate examples/**/scenario.yaml
    python scripts/validate_schemas.py PATH ...   # validate given files, or scenario.yaml under given dirs

Exit codes: 0 = all valid, 1 = validation failure(s), 2 = usage / nothing-to-validate.

Fail-closed: a default (no-args) scan, or a directory scan, that discovers ZERO
scenario files exits 2 -- a gate that validated nothing must not report success.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml  # only third-party dependency; safe_load only

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_GLOB = "examples/**/scenario.yaml"
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


def _display(path: Path) -> str:
    for base in (Path.cwd(), REPO_ROOT):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def validate_file(path: Path) -> list[tuple[str, str, str]]:
    """Parse and validate a single scenario file. Reused by verify.py's scaffold hook."""
    where = _display(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [("yaml-parse-error", where, f"cannot read file: {exc}")]
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [("yaml-parse-error", where, f"YAML parse error: {exc}")]
    return validate_doc(doc, where)


def _discover(paths: list[str], missing: list[str]) -> list[Path] | None:
    """Resolve scenario files to validate.

    - No paths: glob REPO_ROOT/examples/**/scenario.yaml. Zero found -> None.
    - A directory arg: glob scenario.yaml beneath it. Zero found -> None.
    - A file arg: that file.
    Returns the file list, or None to signal a fail-closed "nothing to validate".
    """
    if not paths:
        found = sorted(REPO_ROOT.glob(SCENARIO_GLOB))
        return found or None

    files: list[Path] = []
    saw_empty_dir = False
    for p in paths:
        pp = Path(p)
        pp = pp if pp.is_absolute() else (Path.cwd() / pp)
        if pp.is_dir():
            sub = sorted(pp.glob("**/scenario.yaml"))
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
        description="Validate scenario YAML files (structural; no source resolution).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="scenario files, or dirs to search for scenario.yaml "
             "(default: examples/**/scenario.yaml)",
    )
    args = parser.parse_args(argv)

    missing: list[str] = []
    files = _discover(args.paths, missing)
    if missing:
        for p in missing:
            print(f"error: path not found: {p}", file=sys.stderr)
        return 2
    if files is None:
        target = " ".join(args.paths) if args.paths else SCENARIO_GLOB
        print(
            f"error: no scenario files found ({target}); refusing to report clean.",
            file=sys.stderr,
        )
        return 2

    findings: list[tuple[str, str, str]] = []
    for path in files:
        findings.extend(validate_file(path))

    if findings:
        print(f"schema validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"schema validation OK ({len(files)} scenario file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Centaur harness safety checker (CONSTITUTION §7).

A MINIMUM GATE, not a semantic oracle. Matches a small, curated set of high-signal
patterns for ACTIONABLE operational harm-instructions -- weapons/CBRN/explosive
CONSTRUCTION or SYNTHESIS instructions and explicit step-by-step mass-casualty
how-to. It deliberately does NOT flag strategic assessment (force levels, logistics,
a modeled strike as a scenario event): every rule requires a harm/imperative VERB AND
a weapon/agent OBJECT on the SAME physical line. The gate is line-local -- it will
miss obfuscated, novel, or newline-split content. Treat a clean scan as "no obvious
actionable harm-instruction", not "provably safe".

Patterns are externalized in checks/safety_patterns.yaml (override via the
CENTAUR_SAFETY_PATTERNS env var). The `enabled_tiers` key selects the safe/unsafe
line: `conservative` (default) is construction/synthesis + mass-casualty how-to;
`broader` adds operational targeting/strike-execution detail (higher false-positive
risk on legitimate scenario content). See docs/SAFETY_AND_SCOPE.md.

Usage:
    python scripts/safety_check.py            # scan tracked repo files (git ls-files)
    python scripts/safety_check.py PATH ...   # scan the given files/dirs

Exit codes: 0 = clean, 1 = unsafe match(es) found, 2 = usage / fail-closed (PyYAML or
the patterns file missing / empty / malformed, an unknown tier, zero enabled rules, a
default scan that matches 0 files, or tracked files cannot be listed).

A line containing the marker ``pragma: allowlist safety`` is skipped (escape hatch for
deliberately documented examples). Matched spans are masked in output so the gate
never echoes a full harmful-shaped line into CI logs.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    print(
        "error: PyYAML is required for the safety check; install requirements-dev.txt. "
        "Refusing to report a clean scan.",
        file=sys.stderr,
    )
    raise SystemExit(2)

# Reuse the secret-scan plumbing verbatim (same scripts/ dir; mirrors how
# validate_state imports from validate_claims). REPO_ROOT, file gathering, the
# repo-relative display path, and the mask are identical concerns.
from secret_scan import (
    REPO_ROOT,
    _display,
    _gather_explicit,
    _mask,
    _tracked_files,
)

ALLOWLIST_MARKER = "pragma: allowlist safety"
MAX_BYTES = 1_000_000  # skip files larger than ~1 MB
KNOWN_TIERS = ("conservative", "broader")

PATTERNS_FILE = REPO_ROOT / "checks" / "safety_patterns.yaml"

# The default repo scan (no path args) skips these prefixes. The safety fixtures AND
# this gate's own test file hold DELIBERATE synthetic unsafe samples, and the patterns
# file is the rule DEFINITIONS (it necessarily contains the trigger literals) -- none
# are content to be checked, so the suite scans the fixtures by explicit path instead.
# (Mirrors secret_scan excluding its sample-bearing files.)
DEFAULT_EXCLUDES = (
    "tests/fixtures/safety/",
    "tests/test_safety_check.py",
    "checks/safety_patterns.yaml",
    ".git/",
)


class _FailClosed(Exception):
    """An unusable patterns file; the caller converts this to exit 2."""


def _excluded(rel: str) -> bool:
    return any(rel.startswith(prefix) for prefix in DEFAULT_EXCLUDES)


def _load_rules(path: Path) -> list[tuple[str, re.Pattern[str]]]:
    """Load + compile the safety rules whose tier is enabled.

    Fail-closed: raises _FailClosed on anything that would leave the gate matching
    nothing -- missing/unreadable/malformed file, missing schema_version, absent/empty
    `rules` or `enabled_tiers`, an unknown tier (a typo must not silently disable every
    rule and pass everything), a malformed rule, an uncompilable regex, or an
    enabled-tier set that filters to zero rules. A clean scan must never be reported
    against an unusable rule set.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _FailClosed(f"cannot read patterns file {path}: {exc}")
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise _FailClosed(f"patterns file {path} is not valid YAML: {exc}")
    if not isinstance(doc, dict):
        raise _FailClosed(f"patterns file {path} is not a mapping")

    version = doc.get("schema_version")
    if not isinstance(version, str) or not version.strip():
        raise _FailClosed("patterns file: schema_version is required (non-empty string)")

    tiers = doc.get("enabled_tiers")
    if not isinstance(tiers, list) or not tiers:
        raise _FailClosed("patterns file: enabled_tiers must be a non-empty list")
    unknown_tiers = [t for t in tiers if t not in KNOWN_TIERS]
    if unknown_tiers:
        raise _FailClosed(
            f"patterns file: unknown tier(s) {unknown_tiers} in enabled_tiers "
            f"(known: {list(KNOWN_TIERS)})"
        )
    enabled = set(tiers)

    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        raise _FailClosed("patterns file: 'rules' must be a non-empty list")

    compiled: list[tuple[str, re.Pattern[str]]] = []
    seen_ids: set[str] = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise _FailClosed(f"patterns file: rules[{i}] is not a mapping")
        for key in ("id", "tier", "category", "regex"):
            val = rule.get(key)
            if not isinstance(val, str) or not val.strip():
                raise _FailClosed(f"patterns file: rules[{i}] has missing/empty {key!r}")
        if rule["tier"] not in KNOWN_TIERS:
            raise _FailClosed(
                f"patterns file: rules[{i}] ({rule['id']}) has unknown tier {rule['tier']!r}"
            )
        # Reject duplicate ids across ALL rules (any tier) -- a copy-paste error must
        # fail closed, not silently load two rules under one id.
        if rule["id"] in seen_ids:
            raise _FailClosed(f"patterns file: rules[{i}] has duplicate rule id {rule['id']!r}")
        seen_ids.add(rule["id"])
        if rule["tier"] not in enabled:
            continue
        try:
            pattern = re.compile(rule["regex"])
        except re.error as exc:
            raise _FailClosed(
                f"patterns file: rules[{i}] ({rule['id']}) regex does not compile: {exc}"
            )
        compiled.append((rule["category"], pattern))

    if not compiled:
        raise _FailClosed(
            f"patterns file: no rules match enabled_tiers {tiers}; refusing to scan "
            "with an empty rule set"
        )
    return compiled


def _scan_file(path: Path, rules: list[tuple[str, re.Pattern[str]]]) -> list[tuple[str, str, int, str]]:
    """Return findings as (category, display_path, line_no, masked_span)."""
    findings: list[tuple[str, str, int, str]] = []
    try:
        raw = path.read_bytes()
    except OSError:
        return findings
    if len(raw) > MAX_BYTES or b"\0" in raw:  # skip large / binary files
        return findings
    display = _display(path)
    text = raw.decode("utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOWLIST_MARKER in line:
            continue
        for category, pattern in rules:
            for match in pattern.finditer(line):  # report every match on the line
                # Mask the WHOLE matched span -- the harmful-shaped text is the hazard
                # here (unlike a secret, where only the value is sensitive).
                findings.append((category, display, lineno, _mask(match.group(0))))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="safety_check.py",
        description="Scan files for actionable operational harm-instructions "
        "(a minimum gate, not a semantic oracle).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="files/dirs to scan (default: tracked repo files via git ls-files)",
    )
    args = parser.parse_args(argv)

    patterns_path = Path(os.environ.get("CENTAUR_SAFETY_PATTERNS", str(PATTERNS_FILE)))
    try:
        rules = _load_rules(patterns_path)
    except _FailClosed as exc:
        print(f"error: {exc}. Refusing to report a clean scan.", file=sys.stderr)
        return 2

    if args.paths:
        missing: list[str] = []
        files = _gather_explicit(args.paths, missing)
        if missing:
            for p in missing:
                print(f"error: path not found: {p}", file=sys.stderr)
            return 2
        if not files:
            # An existing-but-empty path is the zero-input fail-open: a check that scanned
            # nothing must never report clean (CONSTITUTION §3; mirrors the default branch
            # and validate_schemas.py's empty-dir guard).
            print("error: the given paths matched 0 files; refusing to report clean.",
                  file=sys.stderr)
            return 2
    else:
        tracked = _tracked_files(REPO_ROOT)
        if tracked is None:
            print(
                "error: could not list tracked files (is git installed and is this a "
                "git repository?). Refusing to report a clean scan.",
                file=sys.stderr,
            )
            return 2
        files = [f for f in tracked if not _excluded(f.relative_to(REPO_ROOT).as_posix())]
        if not files:
            print(
                "error: default scan matched 0 files; refusing to report clean. Pass "
                "explicit paths to scan a non-repo location.",
                file=sys.stderr,
            )
            return 2

    findings: list[tuple[str, str, int, str]] = []
    for f in files:
        findings.extend(_scan_file(f, rules))

    if findings:
        print(
            f"safety check FAILED: {len(findings)} actionable harm-instruction "
            "pattern(s) found:",
            file=sys.stderr,
        )
        for category, display, lineno, masked in findings:
            print(f"  - {category}  {display}:{lineno}  [{masked}]", file=sys.stderr)
        return 1

    print(f"safety check OK ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Centaur source-registry validator (the evidence gate, sources half).

Validates a sources registry (default factbase/sources.yaml): registry shape +
each source entry (structure + tier enum) + unique ids. Reuses the WP1.2 skeleton
engine via a derived entry-spec (registry entries carry no per-entry
schema_version). Structural; the only semantics is the source-tier vocabulary.

Usage:
    python scripts/validate_sources.py            # validate factbase/sources.yaml
    python scripts/validate_sources.py PATH       # validate a given sources registry

Exit codes: 0 = valid, 1 = validation failure(s), 2 = usage / fail-closed
(missing / unreadable / empty registry, non-mapping top level, or a missing /
empty 'sources' list -- a gate that has nothing to validate must not report clean).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Reuse the WP1.2 engine + specs WITHOUT modifying them.
from validate_schemas import (
    REPO_ROOT,
    SOURCE_SPEC,
    _display,
    _is_nonempty_str,
    _validate_skeleton,
)

DEFAULT_SOURCES = REPO_ROOT / "factbase" / "sources.yaml"

# Registry entries have no per-entry schema_version (the registry file holds it),
# so drop it from the reused spec; the tier enum is reused verbatim.
SOURCE_ENTRY_SPEC = {
    "required_str": tuple(f for f in SOURCE_SPEC["required_str"] if f != "schema_version"),
    "required_int": SOURCE_SPEC["required_int"],
    "enums": SOURCE_SPEC["enums"],
}


def load_registry(path: Path) -> tuple[object, str | None]:
    """Return (doc, None) on success, or (None, error) on a fail-closed condition."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read {path}: {exc}"
    try:
        return yaml.safe_load(text), None
    except yaml.YAMLError as exc:
        return None, f"YAML parse error in {path}: {exc}"


def validate_sources(doc: object, where: str) -> list[tuple[str, str, str]]:
    """Validate a (shape-checked) sources registry. Returns (code, where, message)."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not _is_nonempty_str(doc.get("schema_version")):
        add("missing-schema-version",
            "schema_version is required and must be a non-empty string")

    seen: dict[str, str] = {}
    for i, entry in enumerate(doc["sources"]):
        tag = f"sources[{i}]"
        problems.extend(_validate_skeleton(entry, tag, SOURCE_ENTRY_SPEC))
        if isinstance(entry, dict) and _is_nonempty_str(entry.get("id")):
            sid = entry["id"]
            if sid in seen:
                add("duplicate-id", f"{tag} duplicate id {sid!r} (already at {seen[sid]})")
            else:
                seen[sid] = tag
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_sources.py",
        description="Validate a source registry (structural + tier enum + unique ids).",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_SOURCES),
        help="sources registry (default: factbase/sources.yaml)",
    )
    args = parser.parse_args(argv)
    path = Path(args.path)

    doc, err = load_registry(path)
    if err is not None:
        print(f"error: {err}; refusing to report clean.", file=sys.stderr)
        return 2
    if not isinstance(doc, dict) or not isinstance(doc.get("sources"), list) or not doc["sources"]:
        print(
            f"error: {path} is not a usable source registry (need a mapping with a "
            "non-empty 'sources' list); refusing to report clean.",
            file=sys.stderr,
        )
        return 2

    findings = validate_sources(doc, _display(path))
    if findings:
        print(f"source validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"source validation OK ({len(doc['sources'])} sources)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

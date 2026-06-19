#!/usr/bin/env python3
"""Centaur claim-registry validator (the evidence gate, claims half).

Validates a claims registry (default factbase/claims.yaml) against a sources
registry (default factbase/sources.yaml):
  - registry shape + each claim entry (structure + confidence enum) + unique ids;
  - every claim cites >=1 source reference, and every reference resolves to a
    source id in the source registry;
  - the source-tier rule: a top-confidence (CONFIRMED) claim must cite at least one
    non-SOCIAL source (OFFICIAL or MAINSTREAM).

Reuses the WP1.2 skeleton engine via a derived entry-spec. The tier rule is a
MINIMUM gate (it blocks SOCIAL-only top-confidence claims), not a truth oracle.

Usage:
    python scripts/validate_claims.py                          # factbase/claims.yaml vs factbase/sources.yaml
    python scripts/validate_claims.py CLAIMS [--sources SRC]   # explicit registries

Exit codes: 0 = valid, 1 = validation failure(s), 2 = usage / fail-closed
(either registry missing / unreadable / empty / non-mapping, or its list absent /
empty -- including a broken sources registry, since resolution can't be judged).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from validate_schemas import (
    REPO_ROOT,
    CLAIM_SPEC,
    SOURCE_SPEC,
    _display,
    _is_nonempty_str,
    _validate_skeleton,
)

DEFAULT_CLAIMS = REPO_ROOT / "factbase" / "claims.yaml"
DEFAULT_SOURCES = REPO_ROOT / "factbase" / "sources.yaml"

TOP_CONFIDENCE = "CONFIRMED"  # claims at this confidence need >=1 non-SOCIAL source
SOCIAL_TIER = "SOCIAL"
# Require an explicitly RECOGNIZED non-SOCIAL tier (fail-closed): a source with a
# missing / unrecognized tier does NOT satisfy the rule. Derived from the source
# enum so it stays in sync.
NON_SOCIAL_TIERS = frozenset(t for t in SOURCE_SPEC["enums"]["tier"] if t != SOCIAL_TIER)

CLAIM_ENTRY_SPEC = {
    "required_str": tuple(f for f in CLAIM_SPEC["required_str"] if f != "schema_version"),
    "required_int": CLAIM_SPEC["required_int"],
    "enums": CLAIM_SPEC["enums"],
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


def _source_index(sources_doc: dict) -> dict[str, object]:
    """Map source id -> tier from a (shape-checked) sources registry. Duplicate
    source ids collapse to one entry; resolution only needs membership."""
    index: dict[str, object] = {}
    for entry in sources_doc["sources"]:
        if isinstance(entry, dict) and _is_nonempty_str(entry.get("id")):
            index[entry["id"]] = entry.get("tier")
    return index


def validate_claims(doc: object, where: str, source_index: dict) -> list[tuple[str, str, str]]:
    """Validate a (shape-checked) claims registry against the source index."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not _is_nonempty_str(doc.get("schema_version")):
        add("missing-schema-version",
            "schema_version is required and must be a non-empty string")

    seen: dict[str, str] = {}
    for i, claim in enumerate(doc["claims"]):
        tag = f"claims[{i}]"
        problems.extend(_validate_skeleton(claim, tag, CLAIM_ENTRY_SPEC))
        if not isinstance(claim, dict):
            continue

        if _is_nonempty_str(claim.get("id")):
            cid = claim["id"]
            if cid in seen:
                add("duplicate-id", f"{tag} duplicate id {cid!r} (already at {seen[cid]})")
            else:
                seen[cid] = tag

        refs = claim.get("sources")
        ref_list = [r for r in refs if _is_nonempty_str(r)] if isinstance(refs, list) else []
        if not ref_list:
            add("missing-source-ref",
                f"{tag} requires at least one non-empty string source reference")
            continue
        unresolved = [r for r in ref_list if r not in source_index]
        if unresolved:  # one consolidated finding per claim
            listed = ", ".join(repr(r) for r in unresolved)
            add("unresolved-source-ref",
                f"{tag} source(s) {listed} not found in the source registry")
            continue  # tier rule needs resolved tiers

        if claim.get("confidence") == TOP_CONFIDENCE:
            if not any(source_index.get(r) in NON_SOCIAL_TIERS for r in ref_list):
                add("confidence-tier-violation",
                    f"{tag} {TOP_CONFIDENCE} claim must cite >=1 source of a recognized "
                    f"non-{SOCIAL_TIER} tier {sorted(NON_SOCIAL_TIERS)}; cites none")
    return problems


def _usable_registry(doc: object, key: str) -> bool:
    return isinstance(doc, dict) and isinstance(doc.get(key), list) and bool(doc[key])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_claims.py",
        description="Validate a claim registry: resolution to sources + the tier rule.",
    )
    parser.add_argument(
        "claims",
        nargs="?",
        default=str(DEFAULT_CLAIMS),
        help="claims registry (default: factbase/claims.yaml)",
    )
    parser.add_argument(
        "--sources",
        default=str(DEFAULT_SOURCES),
        help="sources registry to resolve against (default: factbase/sources.yaml)",
    )
    args = parser.parse_args(argv)
    claims_path = Path(args.claims)
    sources_path = Path(args.sources)

    # Sources first: resolution cannot be judged against a broken source registry.
    sdoc, serr = load_registry(sources_path)
    if serr is not None or not _usable_registry(sdoc, "sources"):
        reason = serr or f"{sources_path} is not a usable source registry"
        print(f"error: {reason}; cannot resolve claims. refusing to report clean.",
              file=sys.stderr)
        return 2
    source_index = _source_index(sdoc)

    cdoc, cerr = load_registry(claims_path)
    if cerr is not None or not _usable_registry(cdoc, "claims"):
        reason = cerr or (
            f"{claims_path} is not a usable claim registry (need a mapping with a "
            "non-empty 'claims' list)"
        )
        print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
        return 2

    findings = validate_claims(cdoc, _display(claims_path), source_index)
    if findings:
        print(f"claim validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"claim validation OK ({len(cdoc['claims'])} claims, {len(source_index)} sources)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

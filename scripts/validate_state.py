#!/usr/bin/env python3
"""Centaur state validator (the evidence gate, source-or-label half).

Validates a scenario state registry (default the Ukraine example's
initial_state.yaml) against a claims registry (default factbase/claims.yaml):
  - registry shape + each state item (structure + world-vs-game label enum) +
    unique ids;
  - the CONSTITUTION §5 source-or-label rule: a REAL_WORLD_BASELINE item (the only
    label asserting external fact) must cite >=1 claim that resolves to the claim
    registry, or be relabeled ASSUMPTION / MODEL_OUTPUT / ILLUSTRATIVE etc.;
  - any item that DOES carry claim references must have every reference resolve.

State -> claim is checked for RESOLUTION only; a claim's own confidence/source tier
is enforced upstream by validate_claims.py (a separate CI step). Reuses the WP1.2
skeleton engine + the claims validator's load/shape helpers.

Usage:
    python scripts/validate_state.py                          # example initial_state.yaml vs factbase/claims.yaml
    python scripts/validate_state.py STATE [--claims CLAIMS]  # explicit registries

Exit codes: 0 = valid, 1 = validation failure(s), 2 = usage / fail-closed
(either registry missing / unreadable / empty / non-mapping, or its list absent /
empty -- including a broken claims registry, since resolution can't be judged).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from validate_claims import _usable_registry, load_registry
from validate_schemas import (
    REPO_ROOT,
    WORLD_VS_GAME_LABELS,
    _display,
    _is_nonempty_str,
    _valid_iso_date,
    _validate_skeleton,
)

DEFAULT_STATE = REPO_ROOT / "examples" / "ukraine_crimea_logistics" / "initial_state.yaml"
DEFAULT_CLAIMS = REPO_ROOT / "factbase" / "claims.yaml"

STATE_ENTRY_SPEC = {
    "required_str": ("id", "statement"),
    "required_int": (),
    "enums": {"label": WORLD_VS_GAME_LABELS},
}

# Only these labels assert an external real-world fact, so only they must cite claims.
# (Claim confidence -- CONFIRMED/LIKELY -- is enforced on the claims themselves by
# validate_claims, not duplicated here.) Parameterized so +ANALYST_JUDGMENT is one line.
REQUIRES_CLAIMS = frozenset({"REAL_WORLD_BASELINE"})


def _claim_id_set(claims_doc: dict) -> set:
    """Set of claim ids from a (shape-checked) claims registry. Mirrors the entry
    guard in validate_claims._source_index; resolution needs only membership."""
    return {
        entry["id"]
        for entry in claims_doc["claims"]
        if isinstance(entry, dict) and _is_nonempty_str(entry.get("id"))
    }


def validate_state(doc: object, where: str, claim_ids: set) -> list[tuple[str, str, str]]:
    """Validate a (shape-checked) state registry against the claim-id set."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not _is_nonempty_str(doc.get("schema_version")):
        add("missing-schema-version",
            "schema_version is required and must be a non-empty string")

    # as_of_date (CONSTITUTION §6, WP7): optional, but validated if present -- a malformed
    # as-of date is a provenance defect. Shared strict ISO-8601 helper (date-only).
    aod = doc.get("as_of_date")
    if aod is not None and not _valid_iso_date(aod):
        add("invalid-format",
            f"as_of_date {aod!r} must be an ISO-8601 date (YYYY-MM-DD) when present")

    seen: dict[str, str] = {}
    for i, item in enumerate(doc["items"]):
        tag = f"items[{i}]"
        problems.extend(_validate_skeleton(item, tag, STATE_ENTRY_SPEC))
        if not isinstance(item, dict):
            continue

        if _is_nonempty_str(item.get("id")):
            iid = item["id"]
            if iid in seen:
                add("duplicate-id", f"{tag} duplicate id {iid!r} (already at {seen[iid]})")
            else:
                seen[iid] = tag

        refs = item.get("claims")
        ref_list = [r for r in refs if _is_nonempty_str(r)] if isinstance(refs, list) else []

        # Source-or-label rule: an item asserting external fact must cite a claim.
        if item.get("label") in REQUIRES_CLAIMS and not ref_list:
            add("unsupported-baseline",
                f"{tag} a {item['label']} item must cite >=1 claim (resolving to the "
                "claim registry) or be relabeled to a non-REAL_WORLD_BASELINE label")
            continue

        # Resolution runs unconditionally: any present claim ref must resolve.
        unresolved = [r for r in ref_list if r not in claim_ids]
        if unresolved:  # one consolidated finding per item
            listed = ", ".join(repr(r) for r in unresolved)
            add("unresolved-claim-ref",
                f"{tag} claim(s) {listed} not found in the claim registry")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_state.py",
        description="Validate a scenario state registry: source-or-label + resolution.",
    )
    parser.add_argument(
        "state",
        nargs="?",
        default=str(DEFAULT_STATE),
        help="state registry (default: the Ukraine example initial_state.yaml)",
    )
    parser.add_argument(
        "--claims",
        default=str(DEFAULT_CLAIMS),
        help="claims registry to resolve against (default: factbase/claims.yaml)",
    )
    args = parser.parse_args(argv)
    state_path = Path(args.state)
    claims_path = Path(args.claims)

    # Claims first: resolution cannot be judged against a broken claims registry.
    cdoc, cerr = load_registry(claims_path)
    if cerr is not None or not _usable_registry(cdoc, "claims"):
        reason = cerr or f"{claims_path} is not a usable claim registry"
        print(f"error: {reason}; cannot resolve state. refusing to report clean.",
              file=sys.stderr)
        return 2
    claim_ids = _claim_id_set(cdoc)

    sdoc, serr = load_registry(state_path)
    if serr is not None or not _usable_registry(sdoc, "items"):
        reason = serr or (
            f"{state_path} is not a usable state registry (need a mapping with a "
            "non-empty 'items' list)"
        )
        print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
        return 2

    findings = validate_state(sdoc, _display(state_path), claim_ids)
    if findings:
        print(f"state validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"state validation OK ({len(sdoc['items'])} items, {len(claim_ids)} claims)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

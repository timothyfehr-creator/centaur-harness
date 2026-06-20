#!/usr/bin/env python3
"""Centaur event-registry validator (the evidence gate, events half).

Validates an event ledger (default factbase/events.yaml) against a claims registry
(default factbase/claims.yaml):
  - registry shape + each event entry (structure + category & confidence enums) +
    unique ids;
  - every event cites >=1 claim reference, and every reference resolves to a claim
    id in the claims registry.

The structural twin of validate_claims.py (event:claim mirrors claim:source). No
confidence-consistency cross-rule is enforced (WP2.2 is minimal). Reuses the WP1.2
skeleton engine + the claims validator's load/shape helpers.

Usage:
    python scripts/validate_events.py                          # factbase/events.yaml vs factbase/claims.yaml
    python scripts/validate_events.py EVENTS [--claims CLAIMS] # explicit registries

Exit codes: 0 = valid, 1 = validation failure(s), 2 = usage / fail-closed
(either registry missing / unreadable / empty / non-mapping, or its list absent /
empty -- including a broken claims registry, since resolution can't be judged).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from validate_schemas import (
    REPO_ROOT,
    EVENT_SPEC,
    _display,
    _is_nonempty_str,
    _validate_skeleton,
)
from validate_claims import load_registry, _usable_registry

DEFAULT_EVENTS = REPO_ROOT / "factbase" / "events.yaml"
DEFAULT_CLAIMS = REPO_ROOT / "factbase" / "claims.yaml"

EVENT_ENTRY_SPEC = {
    "required_str": tuple(f for f in EVENT_SPEC["required_str"] if f != "schema_version"),
    "required_int": EVENT_SPEC["required_int"],
    "enums": EVENT_SPEC["enums"],
}


def _claim_id_set(claims_doc: dict) -> set:
    """Set of claim ids from a (shape-checked) claims registry. Mirrors the entry
    guard in validate_claims._source_index; resolution needs only membership."""
    return {
        entry["id"]
        for entry in claims_doc["claims"]
        if isinstance(entry, dict) and _is_nonempty_str(entry.get("id"))
    }


def validate_events(doc: object, where: str, claim_ids: set) -> list[tuple[str, str, str]]:
    """Validate a (shape-checked) event ledger against the claim-id set."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not _is_nonempty_str(doc.get("schema_version")):
        add("missing-schema-version",
            "schema_version is required and must be a non-empty string")

    seen: dict[str, str] = {}
    for i, event in enumerate(doc["events"]):
        tag = f"events[{i}]"
        problems.extend(_validate_skeleton(event, tag, EVENT_ENTRY_SPEC))
        if not isinstance(event, dict):
            continue

        if _is_nonempty_str(event.get("id")):
            eid = event["id"]
            if eid in seen:
                add("duplicate-id", f"{tag} duplicate id {eid!r} (already at {seen[eid]})")
            else:
                seen[eid] = tag

        refs = event.get("claims")
        ref_list = [r for r in refs if _is_nonempty_str(r)] if isinstance(refs, list) else []
        if not ref_list:
            add("missing-claim-ref",
                f"{tag} requires at least one non-empty string claim reference")
            continue
        unresolved = [r for r in ref_list if r not in claim_ids]
        if unresolved:  # one consolidated finding per event
            listed = ", ".join(repr(r) for r in unresolved)
            add("unresolved-claim-ref",
                f"{tag} claim(s) {listed} not found in the claim registry")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_events.py",
        description="Validate an event ledger: structure + resolution to claims.",
    )
    parser.add_argument(
        "events",
        nargs="?",
        default=str(DEFAULT_EVENTS),
        help="event ledger (default: factbase/events.yaml)",
    )
    parser.add_argument(
        "--claims",
        default=str(DEFAULT_CLAIMS),
        help="claims registry to resolve against (default: factbase/claims.yaml)",
    )
    args = parser.parse_args(argv)
    events_path = Path(args.events)
    claims_path = Path(args.claims)

    # Claims first: resolution cannot be judged against a broken claims registry.
    cdoc, cerr = load_registry(claims_path)
    if cerr is not None or not _usable_registry(cdoc, "claims"):
        reason = cerr or f"{claims_path} is not a usable claim registry"
        print(f"error: {reason}; cannot resolve events. refusing to report clean.",
              file=sys.stderr)
        return 2
    claim_ids = _claim_id_set(cdoc)

    edoc, eerr = load_registry(events_path)
    if eerr is not None or not _usable_registry(edoc, "events"):
        reason = eerr or (
            f"{events_path} is not a usable event ledger (need a mapping with a "
            "non-empty 'events' list)"
        )
        print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
        return 2

    findings = validate_events(edoc, _display(events_path), claim_ids)
    if findings:
        print(f"event validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"event validation OK ({len(edoc['events'])} events, {len(claim_ids)} claims)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

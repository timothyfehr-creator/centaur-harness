#!/usr/bin/env python3
"""Centaur agent-grounding validator (WP5).

Validates an agent registry (default the Ukraine example's agents.yaml) so agents are
GROUNDED rather than generic chatbots. Each agent must:
  - validate structurally (id / name / type enum, reusing the WP1.2 skeleton);
  - cite >=1 knowledge book that resolves to the knowledge/ catalog;
  - declare >=1 capability whose refs resolve to a claim (factbase/claims.yaml) OR an
    assumption (factbase/assumptions.yaml) -- the grounding bar is knowledge AND a
    resolving capability;
  - have every behavioral_assumption (if present) resolve to an assumption id.

An agent with no resolving knowledge OR no resolving capability is `ungrounded-agent`.
The assumptions registry is structurally validated here (folded in -- it has no separate
gate). Resolution targets (claims, assumptions, the knowledge index) are loaded
fail-closed: a missing / unreadable / empty upstream means resolution cannot be judged,
so the gate refuses to report clean (exit 2). Reuses the claims validator's load/shape
helpers and the schema validator's skeleton engine.

Usage:
    python scripts/validate_agents.py
    python scripts/validate_agents.py AGENTS [--claims C] [--assumptions A] [--knowledge-dir K]

Exit codes: 0 = valid, 1 = validation failure(s), 2 = usage / fail-closed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from validate_schemas import (
    REPO_ROOT,
    AGENT_SPEC,
    _display,
    _is_nonempty_str,
    _validate_skeleton,
)
from validate_claims import load_registry, _usable_registry

DEFAULT_AGENTS = REPO_ROOT / "examples" / "ukraine_crimea_logistics" / "agents.yaml"
DEFAULT_CLAIMS = REPO_ROOT / "factbase" / "claims.yaml"
DEFAULT_ASSUMPTIONS = REPO_ROOT / "factbase" / "assumptions.yaml"
DEFAULT_KNOWLEDGE = REPO_ROOT / "knowledge"

# Per-agent skeleton: AGENT_SPEC minus the registry-level schema_version (the same
# entry-spec idiom validate_sources / validate_claims use).
AGENT_ENTRY_SPEC = {
    "required_str": tuple(f for f in AGENT_SPEC["required_str"] if f != "schema_version"),
    "required_int": AGENT_SPEC["required_int"],
    "enums": AGENT_SPEC["enums"],
}
# Assumptions are mono-label by construction (the registry embodies the §4 ASSUMPTION
# label), so an entry needs only an id + a statement.
ASSUMPTION_ENTRY_SPEC = {"required_str": ("id", "statement"), "required_int": (), "enums": {}}


def _id_set(doc: dict, key: str) -> set:
    """Set of ids from a (shape-checked) registry list. Resolution needs only membership."""
    return {
        entry["id"]
        for entry in doc[key]
        if isinstance(entry, dict) and _is_nonempty_str(entry.get("id"))
    }


def _book_ids(knowledge_dir: Path) -> tuple[set | None, str | None]:
    """Build the knowledge-book id index by globbing knowledge_dir for *.yaml. Returns
    (ids, None) or (None, error). Fail-closed: the index must be trustworthy, so an
    empty dir or any unreadable / non-mapping / id-less book is an error, not a clean
    index (an agent's knowledge refs could otherwise resolve against a broken catalog)."""
    if not knowledge_dir.is_dir():
        return None, f"knowledge dir {knowledge_dir} not found"
    books = sorted(knowledge_dir.glob("**/*.yaml"))
    if not books:
        return None, f"no knowledge books found under {knowledge_dir}"
    # Track id -> path so a DUPLICATE book id is rejected (fail-closed), not silently
    # collapsed: two books sharing an id would let an agent resolve against a corrupt
    # catalog. (Every other resolution target self-checks duplicate ids; books are the
    # only one with no gate of their own, so the index builder must do it.)
    seen: dict[str, Path] = {}
    for path in books:
        doc, err = load_registry(path)
        if err is not None:
            return None, err
        if not isinstance(doc, dict) or not _is_nonempty_str(doc.get("id")):
            return None, f"knowledge book {path} must be a mapping with a non-empty id"
        bid = doc["id"]
        if bid in seen:
            return None, f"duplicate knowledge-book id {bid!r} in {path} (already in {seen[bid]})"
        seen[bid] = path
    return set(seen), None


def validate_assumptions(doc: dict, where: str) -> list[tuple[str, str, str]]:
    """Folded structural validation of the assumptions registry: each entry needs a
    non-empty id + statement, and ids are unique. (Resolution itself is judged against
    the id set; this catches a malformed registry as exit-1 findings.)"""
    problems: list[tuple[str, str, str]] = []
    if not _is_nonempty_str(doc.get("schema_version")):
        problems.append(("missing-schema-version", where,
                         "schema_version is required and must be a non-empty string"))
    seen: dict[str, str] = {}
    for i, entry in enumerate(doc["assumptions"]):
        tag = f"assumptions[{i}]"
        problems.extend(_validate_skeleton(entry, tag, ASSUMPTION_ENTRY_SPEC))
        if isinstance(entry, dict) and _is_nonempty_str(entry.get("id")):
            aid = entry["id"]
            if aid in seen:
                problems.append(("duplicate-id", tag,
                                 f"duplicate id {aid!r} (already at {seen[aid]})"))
            else:
                seen[aid] = tag
    return problems


def validate_agents(doc: dict, where: str, claim_ids: set, assumption_ids: set,
                    book_ids: set) -> list[tuple[str, str, str]]:
    """Validate a (shape-checked) agent registry against the resolution targets."""
    problems: list[tuple[str, str, str]] = []
    ref_targets = claim_ids | assumption_ids  # capability refs resolve to either

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not _is_nonempty_str(doc.get("schema_version")):
        add("missing-schema-version",
            "schema_version is required and must be a non-empty string")

    seen: dict[str, str] = {}
    for i, agent in enumerate(doc["agents"]):
        tag = f"agents[{i}]"
        problems.extend(_validate_skeleton(agent, tag, AGENT_ENTRY_SPEC))
        if not isinstance(agent, dict):
            continue

        if _is_nonempty_str(agent.get("id")):
            aid = agent["id"]
            if aid in seen:
                add("duplicate-id", f"{tag} duplicate id {aid!r} (already at {seen[aid]})")
            else:
                seen[aid] = tag

        # Knowledge: resolve every ref to a book id; >=1 resolving = grounding leg 1.
        krefs = agent.get("knowledge")
        klist = [r for r in krefs if _is_nonempty_str(r)] if isinstance(krefs, list) else []
        kresolved = [r for r in klist if r in book_ids]
        kunresolved = [r for r in klist if r not in book_ids]
        if kunresolved:
            listed = ", ".join(repr(r) for r in kunresolved)
            add("unresolved-knowledge-ref",
                f"{tag} knowledge book(s) {listed} not found in the knowledge catalog")

        # Capabilities: each entry needs a statement; refs resolve to claims | assumptions.
        # >=1 capability with >=1 resolving ref = grounding leg 2.
        caps = agent.get("capabilities")
        cap_list = caps if isinstance(caps, list) else []
        cap_unresolved: list[str] = []
        has_resolving_cap = False
        for j, cap in enumerate(cap_list):
            if not isinstance(cap, dict):
                add("missing-field", f"{tag} capabilities[{j}] must be a mapping with a statement")
                continue
            if not _is_nonempty_str(cap.get("statement")):
                add("missing-field", f"{tag} capabilities[{j}] requires a non-empty statement")
            crefs = cap.get("refs")
            crlist = [r for r in crefs if _is_nonempty_str(r)] if isinstance(crefs, list) else []
            if any(r in ref_targets for r in crlist):
                has_resolving_cap = True
            cap_unresolved.extend(r for r in crlist if r not in ref_targets)
        if cap_unresolved:
            listed = ", ".join(repr(r) for r in cap_unresolved)
            add("unresolved-capability-ref",
                f"{tag} capability ref(s) {listed} not found in claims or assumptions")

        # Behavioral assumptions: resolve-if-present, to assumptions ONLY.
        brefs = agent.get("behavioral_assumptions")
        blist = [r for r in brefs if _is_nonempty_str(r)] if isinstance(brefs, list) else []
        bunresolved = [r for r in blist if r not in assumption_ids]
        if bunresolved:
            listed = ", ".join(repr(r) for r in bunresolved)
            add("unresolved-assumption-ref",
                f"{tag} behavioral assumption(s) {listed} not found in the assumption registry")

        # Grounding bar: knowledge AND a resolving capability (anti-"generic chatbot").
        if not kresolved or not has_resolving_cap:
            legs = []
            if not kresolved:
                legs.append("no resolving knowledge book")
            if not has_resolving_cap:
                legs.append("no capability with a resolving claim/assumption ref")
            add("ungrounded-agent", f"{tag} is ungrounded: {' and '.join(legs)}")
    return problems


def _load_or_fail(path: Path, key: str, role: str) -> tuple[dict | None, int]:
    """Load + shape-check a resolution-target registry. Returns (doc, 0) or (None, 2)."""
    doc, err = load_registry(path)
    if err is not None or not _usable_registry(doc, key):
        reason = err or f"{path} is not a usable {role} registry (need a mapping with a non-empty '{key}' list)"
        print(f"error: {reason}; cannot resolve agents. refusing to report clean.",
              file=sys.stderr)
        return None, 2
    return doc, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_agents.py",
        description="Validate an agent registry: structure + knowledge/evidence/assumption grounding.",
    )
    parser.add_argument("agents", nargs="?", default=str(DEFAULT_AGENTS),
                        help="agent registry (default: the Ukraine example agents.yaml)")
    parser.add_argument("--claims", default=str(DEFAULT_CLAIMS),
                        help="claims registry to resolve capability refs against")
    parser.add_argument("--assumptions", default=str(DEFAULT_ASSUMPTIONS),
                        help="assumptions registry (also structurally validated here)")
    parser.add_argument("--knowledge-dir", default=str(DEFAULT_KNOWLEDGE),
                        help="knowledge-book directory to resolve knowledge refs against")
    args = parser.parse_args(argv)

    # Resolution targets first: resolution cannot be judged against a broken upstream.
    cdoc, rc = _load_or_fail(Path(args.claims), "claims", "claim")
    if rc:
        return rc
    adoc, rc = _load_or_fail(Path(args.assumptions), "assumptions", "assumption")
    if rc:
        return rc
    book_ids, berr = _book_ids(Path(args.knowledge_dir))
    if berr is not None:
        print(f"error: {berr}; cannot resolve agents. refusing to report clean.", file=sys.stderr)
        return 2

    gdoc, gerr = load_registry(Path(args.agents))
    if gerr is not None or not _usable_registry(gdoc, "agents"):
        reason = gerr or (
            f"{args.agents} is not a usable agent registry (need a mapping with a "
            "non-empty 'agents' list)"
        )
        print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
        return 2

    claim_ids = _id_set(cdoc, "claims")
    assumption_ids = _id_set(adoc, "assumptions")

    findings = validate_assumptions(adoc, _display(Path(args.assumptions)))
    findings += validate_agents(gdoc, _display(Path(args.agents)),
                                claim_ids, assumption_ids, book_ids)
    if findings:
        print(f"agent validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"agent validation OK ({len(gdoc['agents'])} agents, {len(book_ids)} books, "
          f"{len(claim_ids)} claims, {len(assumption_ids)} assumptions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

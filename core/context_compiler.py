#!/usr/bin/env python3
"""Centaur fog-of-war context compiler (WP6).

Compiles, for a single agent, the state registry it is permitted to see: the public
baseline plus its own private state -- never another agent's private state. The
adjudicator sees everything. This is the first ``core/`` module; it is a pure,
deterministic library (no RNG, no clock, no environment, inputs never mutated), proven
by tests/test_context_compiler.py rather than wired into a verify.py gate.

Partition layout (per scenario), all the v1 state-registry schema:
    examples/<scenario>/state/public.yaml              # all agents + adjudicator
    examples/<scenario>/state/private/<agent-id>.yaml  # that agent + adjudicator
    examples/<scenario>/state/private/adjudicator.yaml  # adjudicator only

Visibility is the file location. ``load_partition`` is the validated entry point and
fails closed (FogError) on any ambiguity -- so no unowned private state can exist and no
agent can be silently over-privileged.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
# Reuse the gates' load/shape helpers (the established in-repo import pattern: the
# scripts/ validators import each other the same way).
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
from validate_claims import _usable_registry, load_registry  # noqa: E402
from validate_schemas import _is_nonempty_str  # noqa: E402

ADJUDICATOR_ID = "adjudicator"


class FogError(Exception):
    """A fail-closed fog-of-war condition (unknown agent, orphan/unowned private file,
    reserved-id collision, id collision, schema_version mismatch, unusable file)."""


class Partition(NamedTuple):
    public: dict                 # the public state registry
    private: dict[str, dict]     # owner-id -> private state registry (owner = filename stem)


def known_agent_ids(agents_doc: dict) -> set[str]:
    """Agent ids from a (shape-checked) agents.yaml registry. Mirrors
    validate_agents._id_set(doc, "agents") -- kept here so core/ does not depend on a
    gate's private name; keep the two in sync if either changes."""
    return {
        entry["id"]
        for entry in agents_doc.get("agents", [])
        if isinstance(entry, dict) and _is_nonempty_str(entry.get("id"))
    }


def _load_state_file(path: Path) -> dict:
    doc, err = load_registry(path)
    if err is not None or not _usable_registry(doc, "items"):
        raise FogError(err or f"{path} is not a usable state registry "
                              "(need a mapping with a non-empty 'items' list)")
    return doc


def _item_ids(doc: dict) -> list[str]:
    return [it["id"] for it in doc["items"]
            if isinstance(it, dict) and _is_nonempty_str(it.get("id"))]


def load_partition(scenario_dir: Path, agent_ids: set[str]) -> Partition:
    """Read <scenario_dir>/state/public.yaml + private/*.yaml into a validated Partition.

    Fail-closed (FogError), on every path, if: an agent is named ``adjudicator`` (it
    would see everything); public.yaml is missing / unreadable / not a usable registry;
    any private file is unreadable / not a usable registry; a private/<id>.yaml whose
    <id> is neither a known agent id nor ``adjudicator`` (an unowned private file); the
    partition files disagree on schema_version; or an item id is not globally unique
    across public + all private files. (Empty `items:` is rejected by _usable_registry.)
    """
    if ADJUDICATOR_ID in agent_ids:
        raise FogError(f"reserved-id collision: an agent may not be named {ADJUDICATOR_ID!r}")

    state_dir = scenario_dir / "state"
    public = _load_state_file(state_dir / "public.yaml")

    allowed_owners = agent_ids | {ADJUDICATOR_ID}
    private: dict[str, dict] = {}
    private_dir = state_dir / "private"
    for path in sorted(private_dir.glob("*.yaml")) if private_dir.is_dir() else []:
        owner = path.stem
        if owner not in allowed_owners:
            raise FogError(f"unowned private file {path.name}: {owner!r} is not a known "
                           f"agent id or {ADJUDICATOR_ID!r}")
        private[owner] = _load_state_file(path)

    # All partition files must share one schema_version (no silent merge of versions).
    versions = {public["schema_version"]} | {d["schema_version"] for d in private.values()}
    if len(versions) > 1:
        raise FogError(f"partition files disagree on schema_version: {sorted(versions)}")

    # Item ids globally unique across public + all private (no shadowing/collision).
    seen: dict[str, str] = {}
    for where, doc in [("public.yaml", public)] + [(f"private/{k}.yaml", d)
                                                   for k, d in sorted(private.items())]:
        for iid in _item_ids(doc):
            if iid in seen:
                raise FogError(f"duplicate item id {iid!r} in {where} (already in {seen[iid]})")
            seen[iid] = where

    return Partition(public=public, private=private)


def compile_context(agent_id: str, partition: Partition, agent_ids: set[str]) -> dict:
    """Return the state registry visible to one agent (or the adjudicator).

    - agent_id in agent_ids      -> public items + its own private items (if any)
    - agent_id == ADJUDICATOR_ID -> public items + ALL private files' items
    - otherwise                  -> FogError (unknown agent; never a default context)

    Output: {schema_version, as_of_date?, items} -- a valid state registry, public-first
    then private (deterministic order), items shallow-copied so inputs are not mutated.
    """
    if agent_id == ADJUDICATOR_ID:
        visible = sorted(partition.private)            # every private file
    elif agent_id in agent_ids:
        visible = [agent_id] if agent_id in partition.private else []
    else:
        raise FogError(f"unknown agent id {agent_id!r} (not in the agent registry)")

    items = [dict(it) for it in partition.public["items"]]
    for owner in visible:
        items.extend(dict(it) for it in partition.private[owner]["items"])

    context = {"schema_version": partition.public["schema_version"], "items": items}
    if "as_of_date" in partition.public:               # the public as_of_date governs
        context["as_of_date"] = partition.public["as_of_date"]
    return context


def compile_all(partition: Partition, agent_ids: set[str],
                include_adjudicator: bool = True) -> dict[str, dict]:
    """{agent_id -> compiled context} for every agent id (+ the adjudicator by default)."""
    out = {aid: compile_context(aid, partition, agent_ids) for aid in sorted(agent_ids)}
    if include_adjudicator:
        out[ADJUDICATOR_ID] = compile_context(ADJUDICATOR_ID, partition, agent_ids)
    return out

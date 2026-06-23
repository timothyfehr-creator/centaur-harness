#!/usr/bin/env python3
"""Centaur typed engine-state validator (the WP-E0 contract, now enforced).

Validates a scenario's TYPED engine state -- the compute surface the resolver reads and ``reduce()``
writes (``schemas/engine_state.schema.md``) -- as opposed to the prose state registry
(``validate_state.py``, the evidence ledger). Structural + digest-scope only; conservation /
non-negativity are ``reduce()``'s job on the RESULTING state, not checked at rest (schema "Error codes").

Per envelope ``{schema_version, state: {as_of_turn, entities[]}, state_digest?}``:
  - ``schema_version`` present (non-empty string);
  - ``state.as_of_turn`` an integer >= 0 (a bool is rejected);
  - ``state.entities`` a non-empty list; each entity has a non-empty UNIQUE ``id``, a ``type`` in the
    ENTITY_TYPES enum, and a ``fields`` mapping of name -> ``{value: number|str|bool, unit: <non-empty>}``;
  - ``state_digest`` is OPTIONAL at rest -- a bare scenario-input envelope is sealed later by
    ``turn_record.assemble()`` -- but when PRESENT it must be ``{algorithm: sha256, domain: canonical,
    value: <64 hex>}`` and its value must equal ``canon.canonical_digest(state)`` (the digest-scope rule:
    computed over the ``state`` field ONLY).

Usage:
    python scripts/validate_engine_state.py                 # validate examples/**/engine_state.yaml
    python scripts/validate_engine_state.py PATH ...        # validate given files / dirs

Exit codes: 0 = all valid, 1 = validation failure(s), 2 = usage / nothing-to-validate. Fail-closed: a
default or directory scan that discovers ZERO engine_state files exits 2 -- a gate that validated
nothing must not report success.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# scripts/ + core/ on path: reuse the schema validator's helpers and the engine canon digest.
_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
for _p in (str(_SCRIPTS), str(_ROOT / "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml  # noqa: E402

import canon  # noqa: E402  (core/canon.py -- canon-v1 digest; rejects floats)
from validate_schemas import REPO_ROOT, _display, _is_nonempty_str  # noqa: E402

CANONICAL = "engine_state.yaml"

# Entity-type enum (schemas/engine_state.schema.md). WP-E2a additively extended the original
# contested-logistics set {FORCE, ROUTE, ROUTE_SECRET, SINK} with the salvo types STRIKE_FORCE,
# AIR_DEFENSE. Per ADJUDICATION_LEDGER ECI-2 this is an additive, backward-compatible extension:
# the contested golden vector's types remain in the enum, so no schema_version bump is required.
ENTITY_TYPES = ("FORCE", "ROUTE", "ROUTE_SECRET", "SINK", "STRIKE_FORCE", "AIR_DEFENSE")

_HEX64_RE = re.compile(r"[0-9a-f]{64}")


def validate_engine_state(doc: object, where: str) -> list[tuple[str, str, str]]:
    """Validate one typed engine-state envelope. Returns a list of (code, where, message)."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not isinstance(doc, dict):
        add("yaml-parse-error", "top-level YAML must be a mapping")
        return problems

    if not _is_nonempty_str(doc.get("schema_version")):
        add("missing-schema-version", "schema_version is required and must be a non-empty string")

    state = doc.get("state")
    if not isinstance(state, dict):
        add("wrong-type", "state is required and must be a mapping")
        return problems  # nothing else is checkable without it

    aot = state.get("as_of_turn")
    if aot is None:
        add("missing-field", "state.as_of_turn is required")
    elif isinstance(aot, bool) or not isinstance(aot, int):  # bool is a subclass of int -> reject
        add("wrong-type", f"state.as_of_turn must be an integer; got {type(aot).__name__}")
    elif aot < 0:
        add("wrong-type", f"state.as_of_turn must be >= 0; got {aot}")

    entities = state.get("entities")
    if not isinstance(entities, list) or not entities:
        add("missing-field", "state.entities is required and must be a non-empty list")
    else:
        seen: dict[str, str] = {}
        for i, ent in enumerate(entities):
            problems.extend(_validate_entity(ent, f"{where} entities[{i}]", seen))

    # state_digest is optional at rest (a bare input is sealed by assemble()); enforced when present.
    if "state_digest" in doc:
        problems.extend(_validate_digest(doc["state_digest"], state, f"{where} state_digest"))

    return problems


def _validate_entity(ent: object, where: str, seen: dict) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        out.append((code, where, msg))

    if not isinstance(ent, dict):
        add("wrong-type", "entity must be a mapping")
        return out

    eid = ent.get("id")
    if not _is_nonempty_str(eid):
        add("missing-field", "id is required and must be a non-empty string")
    elif eid in seen:
        add("duplicate-id", f"duplicate entity id {eid!r} (already at {seen[eid]})")
    else:
        seen[eid] = where

    etype = ent.get("type")
    if not _is_nonempty_str(etype):
        add("missing-field", "type is required and must be a non-empty string")
    elif etype not in ENTITY_TYPES:
        add("invalid-enum", f"type must be one of {sorted(ENTITY_TYPES)}; got {etype!r}")

    fields = ent.get("fields")
    if not isinstance(fields, dict) or not fields:
        add("missing-field", "fields is required and must be a non-empty mapping")
    else:
        for fname, fval in fields.items():
            if not isinstance(fval, dict):
                add("wrong-type", f"field {fname!r} must be a mapping {{value, unit}}")
                continue
            if "value" not in fval:
                add("missing-field", f"field {fname!r} requires a value")
            elif not isinstance(fval["value"], (int, float, str)):  # bool passes via int
                add("wrong-type",
                    f"field {fname!r} value must be a number, string, or bool; "
                    f"got {type(fval['value']).__name__}")
            if not _is_nonempty_str(fval.get("unit")):
                add("missing-field", f"field {fname!r} requires a non-empty unit string")
    return out


def _validate_digest(digest: object, state: dict, where: str) -> list[tuple[str, str, str]]:
    """Enforce the digest-scope rule: state_digest == canon-v1 digest of the `state` field only."""
    out: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        out.append((code, where, msg))

    if not isinstance(digest, dict):
        add("wrong-type", "state_digest must be a mapping {algorithm, domain, value}")
        return out
    for key in ("algorithm", "domain", "value"):
        if not _is_nonempty_str(digest.get(key)):
            add("missing-field", f"state_digest.{key} is required and must be a non-empty string")
    if out:
        return out

    try:
        expected = canon.canonical_digest(state)
    except canon.CanonError as exc:
        add("digest-scope-violation",
            f"state is not canon-v1 encodable, so its digest cannot be verified ({exc})")
        return out

    if digest["algorithm"] != expected["algorithm"] or digest["domain"] != expected["domain"]:
        add("digest-scope-violation",
            f"state_digest must be {{algorithm: {expected['algorithm']}, domain: {expected['domain']}}}; "
            f"got {{algorithm: {digest['algorithm']!r}, domain: {digest['domain']!r}}}")
    if not _HEX64_RE.fullmatch(digest["value"]):
        add("wrong-type", "state_digest.value must be 64 lowercase hex characters")
    elif digest["value"] != expected["value"]:
        add("digest-scope-violation",
            "state_digest.value does not match the canon-v1 digest of the `state` field "
            "(it must be computed over `state` only, excluding state_digest itself)")
    return out


def validate_file(path: Path) -> list[tuple[str, str, str]]:
    where = _display(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [("yaml-parse-error", where, f"cannot read file: {exc}")]
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [("yaml-parse-error", where, f"YAML parse error: {exc}")]
    return validate_engine_state(doc, where)


def _discover(paths: list[str], missing: list[str]) -> list[Path] | None:
    """Resolve files to validate. No paths: glob examples/**/engine_state.yaml. A dir: glob beneath it.
    A file: that file. Returns the list, or None to signal a fail-closed "nothing to validate"."""
    if not paths:
        found = sorted(REPO_ROOT.glob(f"examples/**/{CANONICAL}"))
        return found or None
    files: list[Path] = []
    saw_empty_dir = False
    for p in paths:
        pp = Path(p)
        pp = pp if pp.is_absolute() else (Path.cwd() / pp)
        if pp.is_dir():
            sub = sorted(pp.glob(f"**/{CANONICAL}"))
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
        prog="validate_engine_state.py",
        description="Validate a scenario's typed engine state (structural + digest-scope).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="files, or dirs to search for engine_state.yaml (default: examples/**/engine_state.yaml)",
    )
    args = parser.parse_args(argv)

    missing: list[str] = []
    files = _discover(args.paths, missing)
    if missing:
        for p in missing:
            print(f"error: path not found: {p}", file=sys.stderr)
        return 2
    if files is None:
        target = " ".join(args.paths) if args.paths else f"examples/**/{CANONICAL}"
        print(f"error: no engine_state files found ({target}); refusing to report clean.",
              file=sys.stderr)
        return 2

    findings: list[tuple[str, str, str]] = []
    for path in files:
        findings.extend(validate_file(path))

    if findings:
        print(f"engine-state validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"engine-state validation OK ({len(files)} engine_state file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

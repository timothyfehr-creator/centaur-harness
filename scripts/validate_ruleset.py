#!/usr/bin/env python3
"""Centaur ruleset validator (WP-E2b1) — structural + provenance for a resolver's rules.yaml.

Validates ``examples/**/rules.yaml`` — the ``{value, source}`` provenance tree a salvo loader flattens
into the int-only ruleset the engine hashes. Enforces:
  - the structural envelope (``schema_version``, ``ruleset_id``, ``ruleset_version``, a non-empty
    ``params`` mapping);
  - the EPISTEMIC-DISCIPLINE rule that EVERY parameter leaf carries a non-empty ``source`` tag (no number
    without a citation / ASSUMED tag) — walked recursively, since a ruleset may nest (e.g.
    ``p_intercept_pct.drone``);
  - that no leaf value is a FLOAT (canon-v1 is float-free; a float would crash the engine digest).

Resolver-SPECIFIC bounds (``0<=pct<=100``, ``per>=1``, ...) are enforced in the resolver's ``validate_all``
(a bad ruleset there is a REJECTED transition, not a crash). This gate is the at-rest structure /
provenance check, resolver-agnostic.

Usage:
    python scripts/validate_ruleset.py                 # validate examples/**/rules.yaml
    python scripts/validate_ruleset.py PATH ...        # validate given files / dirs

Exit codes: 0 = all valid, 1 = validation failure(s), 2 = usage / nothing-to-validate (fail-closed: a
default or directory scan that discovers ZERO rules.yaml exits 2).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _p in (str(_SCRIPTS), str(_SCRIPTS.parent / "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml  # noqa: E402

from validate_schemas import REPO_ROOT, _display, _is_nonempty_str  # noqa: E402

CANONICAL = "rules.yaml"


def _is_canon_scalar(v: object) -> bool:
    """A canon-safe leaf value: int / str / bool, or a list of those. NO float (bool is an int subclass)."""
    if isinstance(v, bool) or isinstance(v, int) or isinstance(v, str):
        return True
    if isinstance(v, list):
        return all(_is_canon_scalar(x) for x in v)
    return False


def _has_float(v: object) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, float):
        return True
    if isinstance(v, list):
        return any(_has_float(x) for x in v)
    if isinstance(v, dict):
        return any(_has_float(x) for x in v.values())
    return False


def _walk_params(node: object, where: str, path: str, problems: list) -> None:
    """Walk the {value, source} tree. A leaf is a mapping with a ``value`` key (+ a required ``source``);
    any other mapping is a grouping to recurse into."""
    def add(code: str, msg: str) -> None:
        problems.append((code, where, f"{path}: {msg}"))

    if not isinstance(node, dict):
        add("wrong-type", "param node must be a mapping")
        return
    if "value" in node:                       # a leaf
        v = node["value"]
        if _has_float(v):
            add("float-not-allowed", f"value {v!r} contains a float (canon-v1 is float-free)")
        elif not _is_canon_scalar(v):
            add("wrong-type", f"value {v!r} must be int/str/bool or a list of those")
        if not _is_nonempty_str(node.get("source")):
            add("missing-source",
                "a non-empty `source` provenance tag is required (no number without a citation/ASSUMED tag)")
    else:                                     # a grouping -> recurse
        if not node:
            add("missing-field", "empty param grouping")
        for key, child in node.items():
            _walk_params(child, where, f"{path}.{key}", problems)


def validate_ruleset(doc: object, where: str) -> list:
    problems: list = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not isinstance(doc, dict):
        add("yaml-parse-error", "top-level YAML must be a mapping")
        return problems
    for field in ("schema_version", "ruleset_id", "ruleset_version"):
        if not _is_nonempty_str(doc.get(field)):
            code = "missing-schema-version" if field == "schema_version" else "missing-field"
            add(code, f"{field} is required and must be a non-empty string")

    params = doc.get("params")
    if not isinstance(params, dict) or not params:
        add("missing-field", "params is required and must be a non-empty mapping")
    else:
        for name, node in params.items():
            _walk_params(node, where, f"params.{name}", problems)
    return problems


def validate_file(path: Path) -> list:
    where = _display(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [("yaml-parse-error", where, f"cannot read file: {exc}")]
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [("yaml-parse-error", where, f"YAML parse error: {exc}")]
    return validate_ruleset(doc, where)


def _discover(paths: list, missing: list) -> list | None:
    if not paths:
        found = sorted(REPO_ROOT.glob(f"examples/**/{CANONICAL}"))
        return found or None
    files: list = []
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


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_ruleset.py",
        description="Validate a resolver ruleset (structural + {value, source} provenance; float-free).",
    )
    parser.add_argument("paths", nargs="*",
                        help="files, or dirs to search for rules.yaml (default: examples/**/rules.yaml)")
    args = parser.parse_args(argv)

    missing: list = []
    files = _discover(args.paths, missing)
    if missing:
        for p in missing:
            print(f"error: path not found: {p}", file=sys.stderr)
        return 2
    if files is None:
        target = " ".join(args.paths) if args.paths else f"examples/**/{CANONICAL}"
        print(f"error: no rules.yaml found ({target}); refusing to report clean.", file=sys.stderr)
        return 2

    findings: list = []
    for path in files:
        findings.extend(validate_file(path))

    if findings:
        print(f"ruleset validation FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1

    print(f"ruleset validation OK ({len(files)} rules.yaml file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

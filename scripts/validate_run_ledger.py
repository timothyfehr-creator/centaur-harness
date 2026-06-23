#!/usr/bin/env python3
"""Centaur run-ledger validator (WP7, CONSTITUTION §6).

Validates a per-scenario run_ledger.yaml that PINS reproducibility provenance: a sha256
content hash of every declared input artifact, the git code_version, an ISO as_of_date,
and tool/schema versions. The default mode is a LOCKFILE DRIFT GATE -- it validates the
ledger's structure, then recomputes the live declared-input hashes and confirms the
committed ledger still reproduces. `--write` regenerates the ledger from the current repo.

Declared inputs (the reproducibility surface): the scenario's scenario/agents/initial_state,
its engine_state.yaml + rules.yaml (engine scenarios), its state/ partition, plus factbase/*.yaml
and knowledge/**/*.yaml. (The committed turn record under run/turns/ is a derived OUTPUT, gated by
the turn-replay gate, not pinned here.)

LOCKFILE DISCIPLINE: adding / editing / removing ANY declared-input file makes the committed
ledger stale (CI hash-mismatch / extra-input / missing-input). Re-run with `--write` and
commit the refreshed run_ledger.yaml. (See schemas/run_ledger.schema.md, docs/RUNBOOK.md.)

Usage:
    python scripts/validate_run_ledger.py                  # verify the committed ledger
    python scripts/validate_run_ledger.py --write          # regenerate it from the current repo
    python scripts/validate_run_ledger.py LEDGER [--scenario-dir DIR] [--write]

Exit codes: 0 = verified, 1 = findings (structure or drift), 2 = usage / fail-closed.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import yaml
from validate_claims import _usable_registry, load_registry
from validate_schemas import REPO_ROOT, _display, _is_nonempty_str, _valid_iso_date

DEFAULT_SCENARIO = REPO_ROOT / "examples" / "ukraine_crimea_logistics"
DEFAULT_LEDGER = DEFAULT_SCENARIO / "run_ledger.yaml"
SCHEMA_VERSION = "1.0"
TOOL_VERSION = "1.0"
REQUIRED_STR_FIELDS = ("schema_version", "code_version", "tool_version", "generated_by")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
REGEN_HINT = ("hint: re-run '.venv/bin/python scripts/validate_run_ledger.py --write' "
              "and commit run_ledger.yaml")
_INTEGRITY_CODES = ("hash-mismatch", "missing-input", "extra-input")


def declared_inputs(scenario_dir: Path, repo_root: Path) -> list[Path]:
    """The declared input artifacts a run consumes, sorted by repo-root POSIX path (one
    canonical order). Globs are resolved live; only existing files are returned."""
    paths = [
        scenario_dir / "scenario.yaml",
        scenario_dir / "agents.yaml",
        scenario_dir / "initial_state.yaml",
        scenario_dir / "engine_state.yaml",     # engine scenarios: the typed compute surface (RTH-1)
        scenario_dir / "rules.yaml",             # engine scenarios: the resolver params (RTH-1)
        scenario_dir / "state" / "public.yaml",
    ]
    paths += sorted((scenario_dir / "state" / "private").glob("*.yaml"))
    paths += sorted((repo_root / "factbase").glob("*.yaml"))
    paths += sorted((repo_root / "knowledge").glob("**/*.yaml"))
    existing = {p for p in paths if p.is_file()}
    return sorted(existing, key=lambda p: p.relative_to(repo_root).as_posix())


def _sha256(path: Path) -> str:
    """sha256 of a file's raw bytes (content-only; deterministic; no normalization)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha(root: Path, inputs: list[Path]) -> str | None:
    """git HEAD sha, with a '-dirty' suffix when any DECLARED INPUT is uncommitted (so
    code_version cannot silently lie about which commit produced the hashed bytes). The
    dirty check is scoped to the inputs, not the whole tree -- new tooling files do not
    make the recorded provenance dirty. None if git is unavailable -- the caller fails
    closed. (Mirrors secret_scan._tracked_files's subprocess pattern.)"""
    try:
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    rels = [p.relative_to(root).as_posix() for p in inputs]
    try:
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", *rels],
                               capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        dirty = ""
    return f"{sha}-dirty" if dirty else sha


def validate_structure(doc: dict, where: str) -> list[tuple[str, str, str]]:
    """Structural validation of the ledger document (no disk access)."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    for field in REQUIRED_STR_FIELDS:
        if not _is_nonempty_str(doc.get(field)):
            add("missing-field", f"{field} is required and must be a non-empty string")
    aod = doc.get("as_of_date")
    if not _is_nonempty_str(aod):
        add("missing-field", "as_of_date is required and must be a non-empty string")
    elif not _valid_iso_date(aod):
        add("invalid-format", f"as_of_date {aod!r} must be an ISO-8601 date (YYYY-MM-DD)")
    for placeholder in ("rng_seeds", "llm_steps"):
        if placeholder in doc and doc[placeholder] is not None:
            add("invalid-format",
                f"{placeholder} must be null: the engine is DETERMINISTIC (no RNG draws) and has no "
                f"LLM-assisted step; populating these awaits a future REVIEWED WP (stochastic resolver / "
                f"LLM tier), not an in-place change. got {doc[placeholder]!r}")
    for i, entry in enumerate(doc["inputs"]):
        tag = f"inputs[{i}]"
        if not isinstance(entry, dict):
            add("missing-field", f"{tag} must be a mapping with path + sha256")
            continue
        if not _is_nonempty_str(entry.get("path")):
            add("missing-field", f"{tag} path is required and must be a non-empty string")
        sha = entry.get("sha256")
        if not _is_nonempty_str(sha):
            add("missing-field", f"{tag} sha256 is required and must be a non-empty string")
        elif not _SHA256_RE.fullmatch(sha):
            add("invalid-format", f"{tag} sha256 {sha!r} must be 64 lowercase hex chars")
    return problems


def validate_integrity(doc: dict, where: str, scenario_dir: Path,
                       repo_root: Path) -> list[tuple[str, str, str]]:
    """Recompute the live declared-input hashes and diff against the (structurally valid)
    ledger -- the lockfile drift check. Assumes validate_structure already passed."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    recorded = {e["path"]: e["sha256"] for e in doc["inputs"]}
    live = {p.relative_to(repo_root).as_posix(): p
            for p in declared_inputs(scenario_dir, repo_root)}
    for path in sorted(recorded.keys() - live.keys()):
        add("missing-input", f"recorded input {path!r} is not present on disk")
    for path in sorted(live.keys() - recorded.keys()):
        add("extra-input", f"declared input {path!r} is on disk but not pinned in the ledger")
    for path in sorted(recorded.keys() & live.keys()):
        actual = _sha256(live[path])
        if actual != recorded[path]:
            add("hash-mismatch",
                f"{path} content changed (recorded {recorded[path][:12]}..., now {actual[:12]}...)")
    return problems


def _write_ledger(ledger_path: Path, scenario_dir: Path, repo_root: Path,
                  inputs: list[Path]) -> int:
    sha = _git_sha(repo_root, inputs)
    if sha is None:
        print("error: git unavailable; cannot record code_version. Refusing to write a "
              "ledger without provenance.", file=sys.stderr)
        return 2
    # Build the dict in the intended top-level order; emit with a PINNED serializer so the
    # committed bytes are stable (sort_keys=False keeps order; width avoids hash line-wrap).
    ledger = {
        "schema_version": SCHEMA_VERSION,
        "as_of_date": datetime.date.today().isoformat(),
        "code_version": sha,
        "tool_version": TOOL_VERSION,
        "generated_by": "validate_run_ledger.py --write",
        "inputs": [{"path": p.relative_to(repo_root).as_posix(), "sha256": _sha256(p)}
                   for p in inputs],
        "rng_seeds": None,
        "llm_steps": None,
    }
    ledger_path.write_text(
        yaml.safe_dump(ledger, sort_keys=False, default_flow_style=False,
                       allow_unicode=True, width=4096),
        encoding="utf-8",
    )
    print(f"wrote {_display(ledger_path)} ({len(inputs)} inputs)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_run_ledger.py",
        description="Validate (or --write) a reproducibility run-ledger: structure + input-hash drift.",
    )
    parser.add_argument("ledger", nargs="?", default=str(DEFAULT_LEDGER),
                        help="run-ledger path (default: the Ukraine example run_ledger.yaml)")
    parser.add_argument("--scenario-dir", default=None,
                        help="scenario dir whose inputs the ledger pins (default: the ledger's dir)")
    parser.add_argument("--write", action="store_true",
                        help="regenerate the ledger from the current repo (the only mutating mode)")
    args = parser.parse_args(argv)

    # Resolve to absolute paths up front: declared_inputs() computes each input's
    # path.relative_to(repo_root), which raises ValueError if scenario_dir is relative
    # while repo_root is absolute. A user invoking the documented `LEDGER` form with a
    # relative path must get a verdict, not a traceback.
    ledger_path = Path(args.ledger).resolve()
    scenario_dir = (Path(args.scenario_dir) if args.scenario_dir else ledger_path.parent).resolve()
    repo_root = scenario_dir.parent.parent  # examples/<name> -> repo root

    if args.write:
        inputs = declared_inputs(scenario_dir, repo_root)
        if not inputs:
            print(f"error: no declared inputs under {scenario_dir}; refusing to write an "
                  "empty ledger.", file=sys.stderr)
            return 2
        return _write_ledger(ledger_path, scenario_dir, repo_root, inputs)

    doc, err = load_registry(ledger_path)
    if err is not None or not _usable_registry(doc, "inputs"):
        reason = err or (f"{ledger_path} is not a usable run-ledger (need a mapping with a "
                         "non-empty 'inputs' list)")
        print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
        return 2

    where = _display(ledger_path)
    # Structure first; on a structural fault, stop (so structural fixtures are single-fault
    # and integrity never runs against a malformed inputs list).
    problems = validate_structure(doc, where)
    if not problems:
        inputs = declared_inputs(scenario_dir, repo_root)
        if not inputs:
            print(f"error: no declared inputs under {scenario_dir}; cannot verify the ledger.",
                  file=sys.stderr)
            return 2
        problems = validate_integrity(doc, where, scenario_dir, repo_root)

    if problems:
        print(f"run-ledger validation FAILED: {len(problems)} problem(s):", file=sys.stderr)
        for code, w, msg in problems:
            print(f"  - {code}  {w}  {msg}", file=sys.stderr)
        if any(code in _INTEGRITY_CODES for code, _, _ in problems):
            print("  the committed run_ledger.yaml no longer matches the declared inputs on "
                  "disk (lockfile drift).", file=sys.stderr)
            print(f"  {REGEN_HINT}", file=sys.stderr)
        return 1

    print(f"run-ledger OK ({len(doc['inputs'])} inputs verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

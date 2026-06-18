#!/usr/bin/env python3
"""Centaur harness verification entry point.

Currently implements only ``scaffold`` mode (repo-level integrity).

Modes that belong to later work packages -- ``draft`` and ``release`` -- are
intentionally NOT implemented yet (see IMPLEMENTATION_PLAN_V2.md). They are
treated as unknown modes and fail clearly with a nonzero exit code, so the
harness never falsely reports analytical or release validity.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repo root = parent of the scripts/ directory containing this file. Computed
# from __file__ so verification works regardless of the current directory.
REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_MODES = ("scaffold",)
DEFAULT_MODE = "scaffold"

# Files / directories that must exist for the scaffold to be considered intact.
# Keep this list minimal and repo-level only. Do NOT add scenario, factbase, or
# schema requirements here -- those belong to later work packages, and scaffold
# mode must not require a fully sourced scenario.
REQUIRED_PATHS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/CONSTITUTION.md",
    "docs/COMMAND_SAFETY.md",
    "scripts/verify.py",
    "tests",
    ".github/workflows/ci.yml",
    ".gitignore",
)


def verify_scaffold(repo_root: Path) -> list[str]:
    """Return a list of human-readable problems. An empty list means OK."""
    problems: list[str] = []
    for rel in REQUIRED_PATHS:
        if not (repo_root / rel).exists():
            problems.append(f"missing required path: {rel}")
    problems.extend(_scaffold_schema_problems(repo_root))
    return problems


def _scaffold_schema_problems(repo_root: Path) -> list[str]:
    """Structurally validate any scenario files that exist.

    Scaffold does NOT require a scenario, but it must FAIL CLOSED on one that is
    present yet cannot be validated (e.g. PyYAML missing) -- never silently pass.
    Sourcing is out of scope here (WP2.3); this is structural only.
    """
    scenarios = sorted(repo_root.glob("examples/**/scenario.yaml"))
    if not scenarios:
        return []  # scenarios are not required at scaffold time

    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import validate_schemas  # imports PyYAML at module top
    except Exception as exc:  # PyYAML or module unavailable -> fail closed
        return [f"scenario schema: cannot validate scenarios ({exc})"]

    problems: list[str] = []
    for path in scenarios:
        rel = path.relative_to(repo_root).as_posix()
        for code, _where, msg in validate_schemas.validate_file(path):
            problems.append(f"scenario schema [{rel}]: {code}: {msg}")
    return problems


def run(mode: str, repo_root: Path) -> int:
    """Run the requested verification mode. Returns a process exit code."""
    if mode == "scaffold":
        problems = verify_scaffold(repo_root)
        if problems:
            print("scaffold verification FAILED:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print("scaffold verification OK")
        return 0

    # Unknown or not-yet-implemented mode (e.g. draft, release). Fail clearly.
    print(
        f"error: unknown mode {mode!r}. valid modes: {', '.join(VALID_MODES)}",
        file=sys.stderr,
    )
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="Centaur harness verification (scaffold mode only, for now).",
    )
    # No argparse `choices` here on purpose: we want a custom, descriptive error
    # for unknown modes (handled in run()), and we want main() to be unit-test
    # friendly by returning an exit code rather than raising SystemExit.
    parser.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        help=(
            f"verification mode (default: {DEFAULT_MODE}). "
            f"valid: {', '.join(VALID_MODES)}"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args.mode, REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())

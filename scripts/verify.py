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

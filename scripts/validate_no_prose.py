#!/usr/bin/env python3
"""Global no-prose gate (WP-A1b amendment 3) — no model prose anywhere in the committed repo.

The external review: gitignore is "a speed bump, not a control" (``git add -f`` exists), and a prose gate
scoped to ``run/llm/*.json`` leaves adjacent manholes (a raw dump, probe, or debug capture committed under
``run/raw/``, ``logs/``, ``tmp/``, a stray ``debug.json``). So the prose quarantine is enforced GLOBALLY:
NO committed (git-tracked) file anywhere may contain a provider response ``content[]`` block of type
``text``/``thinking``/``redacted_thinking`` with a non-empty string payload. Committed response bytes are
redacted at source (``core/response_redact.py``); the full wire bytes live run-local + gitignored.

A small EXEMPTION list covers the deliberate prose-bearing TEST fixtures (a fixture WITH prose is needed to
prove the redactor strips it) — exactly as ``secret_scan.py`` exempts its own secret fixtures.

Exit codes: 0 = clean, 1 = prose found in a committed file, 2 = git unavailable (fail-closed).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from response_redact import contains_prose  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
# Deliberate prose-bearing fixtures (test INPUTS standing in for a raw model response, redacted before any
# commit) + this gate's own fixtures. Everything else must be prose-free.
EXEMPT_PREFIXES = (
    "tests/fixtures/agent_bytes/",   # hand-authored "model responses" the drive redacts before committing
    "tests/fixtures/no_prose/",      # this gate's own valid/invalid fixtures
)


def _tracked_files(root: Path) -> list[str] | None:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files"],
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return [ln for ln in out.splitlines() if ln]


def scan(root: Path) -> list[tuple[str, str]]:
    """Return (path, prose_excerpt) for every tracked, non-exempt file carrying response prose."""
    findings: list[tuple[str, str]] = []
    files = _tracked_files(root)
    if files is None:
        raise RuntimeError("git unavailable")
    for rel in files:
        if any(rel.startswith(p) for p in EXEMPT_PREFIXES):
            continue
        path = root / rel
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b'"type"' not in raw or b'content' not in raw:   # cheap pre-filter (most files can't match)
            continue
        for prose in contains_prose(raw):
            findings.append((rel, prose[:60]))
            break
    return findings


def main(argv: list[str] | None = None) -> int:
    try:
        findings = scan(REPO_ROOT)
    except RuntimeError as exc:
        print(f"error: {exc}; refusing to report clean.", file=sys.stderr)
        return 2
    if findings:
        print(f"no-prose gate FAILED: {len(findings)} committed file(s) carry model prose:", file=sys.stderr)
        for rel, excerpt in findings:
            print(f"  - prose-in-committed-file  {rel}  {excerpt!r}", file=sys.stderr)
        print("  committed artifacts must be prose-free (redact at source; keep wire bytes run-local).",
              file=sys.stderr)
        return 1
    print("no-prose OK (no model prose in any committed file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

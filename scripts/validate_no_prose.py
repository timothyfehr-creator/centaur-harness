#!/usr/bin/env python3
"""Global no-prose gate (WP-A1b amendment 3) — no model prose anywhere in the committed repo.

The external review: gitignore is "a speed bump, not a control" (``git add -f`` exists), and a prose gate
scoped to ``run/llm/*.json`` leaves adjacent manholes (a raw dump, probe, or debug capture committed under
``run/raw/``, ``logs/``, ``tmp/``, a stray ``debug.json``). So the prose quarantine is enforced GLOBALLY: no
committed (git-tracked) file anywhere may carry MODEL-RESPONSE prose. "Response prose" is defined by
``core/response_redact.contains_prose`` and the scope is exactly what the redactor emits — a committed
response body (found at the top level, nested under a key, or inside a JSON array; BOM-tolerant) may contain
ONLY skeletal ``tool_use`` command blocks; any string in a non-``tool_use`` block, a ``tool_use`` SIBLING
field, or a ``tool_use`` ``input`` outside the command enum tokens is prose. (It does NOT police free prose
in some OTHER shape — a markdown transcript, a ``{"reasoning": "..."}`` field — those are the separately
VETOED forbidden artifacts, by convention, not this gate's job.) Committed response bytes are redacted at
source (``core/response_redact.py``); the full wire bytes live run-local + gitignored.

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
# A response body is KB-scale; this cap only bounds the read of a pathological large committed file (Centaur
# commits none). It is a RESOURCE guard, not a content filter -- it never decides prose-vs-clean.
_MAX_SCAN_BYTES = 10_000_000


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
            if path.stat().st_size > _MAX_SCAN_BYTES:   # resource guard only (a response body is KB-scale);
                continue                                 # NOT a content filter -- see below.
            raw = path.read_bytes()
        except OSError:
            continue
        # No key-byte pre-filter: ``"content"``/``"type"`` can be \u-escaped (the JSON still parses as a
        # response with prose), which a literal-byte filter skips -- a fail-OPEN against "ANY committed file".
        # contains_prose json.loads-es safely and returns [] for any non-response file, so just call it.
        # Tolerate a leading UTF-8 BOM (PowerShell/Windows/loggers emit one) before the brace check + a
        # JSON ARRAY of response bodies -- both parse as prose-bearing responses; skipping them fails OPEN.
        head = raw.lstrip()
        if head[:3] == b"\xef\xbb\xbf":
            head = head[3:].lstrip()
        if head[:1] not in (b"{", b"["):   # a response body (or an array/wrapper of them) is JSON; escape-proof
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
    print("no-prose OK (no model-response prose in any committed file)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

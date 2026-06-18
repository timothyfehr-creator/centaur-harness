#!/usr/bin/env python3
"""Centaur harness secret scanner.

A minimal, dependency-free secret scanner for long-running coding sessions. It is
a MINIMUM GATE, not a semantic oracle: it matches a curated set of high-precision
patterns (based on gitleaks / detect-secrets rules) plus one precise generic
"keyword = value" rule. It will miss obfuscated or novel secrets -- treat a clean
scan as "no obvious secret", not "provably secret-free".

Usage:
    python scripts/secret_scan.py            # scan tracked repo files (git ls-files)
    python scripts/secret_scan.py PATH ...   # scan the given files/dirs

Exit codes: 0 = clean, 1 = secret(s) found, 2 = usage error.

A line containing the marker ``pragma: allowlist secret`` is skipped (escape hatch
for documented examples and test fixtures). Matched values are masked in output so
the scanner never echoes a secret into CI logs.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWLIST_MARKER = "pragma: allowlist secret"

# The default repo scan (no path args) skips these prefixes. The secret-scan
# fixtures AND this scanner's own test file contain DELIBERATE fake secrets, so
# they must not fail the repo-level scan; the test suite scans the fixtures by
# explicit path instead. (Excluding test sample-secret paths is standard practice
# in gitleaks / detect-secrets.)
DEFAULT_EXCLUDES = (
    "tests/fixtures/secret_scan/",
    "tests/test_secret_scan.py",
    ".git/",
)

MAX_BYTES = 1_000_000  # skip files larger than ~1 MB

# --- Service-specific rules ------------------------------------------------------
# Each literal prefix below is immediately followed by a regex character class
# (e.g. ``[A-Za-z0-9]``) in this source, so these patterns do NOT match their own
# definition text -- the scanner is self-immune. A full-repo scan is run in CI and
# during development to confirm this.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key-id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),
    ("github-fine-grained-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b")),
    ("google-api-key", re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe-secret-key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("anthropic-api-key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{24,}\b")),
    ("openai-api-key", re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}\b")),
    ("private-key-block", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
)

# --- Generic "<keyword> = <high-entropy value>" rule -----------------------------
_GENERIC = re.compile(
    r"(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?key|client[_-]?secret|"
    r"auth[_-]?token|token|password|passwd)"
    r"\s*[:=]\s*"
    r"['\"]?(?P<value>[A-Za-z0-9_\-./+]{16,})['\"]?",
    re.IGNORECASE,
)

# Substrings that mark a value as a placeholder / non-secret. Checked case-folded.
_PLACEHOLDERS = (
    "your_", "your-", "yourkey", "example", "changeme", "change_me", "placeholder",
    "dummy", "sample", "fake", "test", "xxxx", "redacted", "none", "null",
    "${", "{{", "os.environ", "getenv", "process.env", "...", "abc123",
)


def _is_secret_value(value: str) -> bool:
    """Heuristic for the generic rule: reject placeholders and low-diversity
    strings so ordinary prose / identifiers don't trip the scanner."""
    low = value.lower()
    if any(p in low for p in _PLACEHOLDERS):
        return False
    classes = sum(
        bool(re.search(pat, value)) for pat in (r"[a-z]", r"[A-Z]", r"[0-9]")
    )
    return classes >= 2


def _mask(matched: str) -> str:
    """Mask a matched secret so it is never printed in full."""
    if len(matched) <= 8:
        return (matched[0] + "…") if matched else "…"
    return f"{matched[:4]}…{matched[-2:]}"


def _tracked_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [root / rel for rel in out.split("\0") if rel]


def _gather(paths: list[str], root: Path, missing: list[str]) -> list[Path]:
    """Resolve the file list to scan.

    - Explicit paths: scan exactly those (recursing dirs); DEFAULT_EXCLUDES are
      NOT applied, so callers/tests can target the fixtures directly.
    - No paths: tracked files (``git ls-files``) minus DEFAULT_EXCLUDES.
    """
    if paths:
        files: list[Path] = []
        for p in paths:
            pp = Path(p)
            pp = pp if pp.is_absolute() else (Path.cwd() / pp)
            if pp.is_dir():
                files.extend(sorted(f for f in pp.rglob("*") if f.is_file()))
            elif pp.is_file():
                files.append(pp)
            else:
                missing.append(p)
        return [f for f in files if "/.git/" not in f.as_posix()]

    files = []
    for f in _tracked_files(root):
        rel = f.relative_to(root).as_posix()
        if any(rel.startswith(prefix) for prefix in DEFAULT_EXCLUDES):
            continue
        files.append(f)
    return files


def _display(path: Path) -> str:
    for base in (Path.cwd(), REPO_ROOT):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def _scan_file(path: Path) -> list[tuple[str, str, int, str]]:
    """Return findings as (rule, display_path, line_no, masked_value)."""
    findings: list[tuple[str, str, int, str]] = []
    try:
        raw = path.read_bytes()
    except OSError:
        return findings
    if len(raw) > MAX_BYTES or b"\0" in raw:  # skip large / binary files
        return findings
    display = _display(path)
    text = raw.decode("utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOWLIST_MARKER in line:
            continue
        for name, pattern in _RULES:
            match = pattern.search(line)
            if match:
                findings.append((name, display, lineno, _mask(match.group(0))))
        gmatch = _GENERIC.search(line)
        if gmatch and _is_secret_value(gmatch.group("value")):
            findings.append(
                ("generic-assignment", display, lineno, _mask(gmatch.group("value")))
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="secret_scan.py",
        description="Scan files for obvious secrets (a minimum gate, not an oracle).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="files/dirs to scan (default: tracked repo files via git ls-files)",
    )
    args = parser.parse_args(argv)

    missing: list[str] = []
    files = _gather(args.paths, REPO_ROOT, missing)
    if missing:
        for p in missing:
            print(f"error: path not found: {p}", file=sys.stderr)
        return 2

    findings: list[tuple[str, str, int, str]] = []
    for f in files:
        findings.extend(_scan_file(f))

    if findings:
        print(
            f"secret scan FAILED: {len(findings)} potential secret(s) found:",
            file=sys.stderr,
        )
        for name, display, lineno, masked in findings:
            print(f"  - {name}  {display}:{lineno}  [{masked}]", file=sys.stderr)
        return 1

    print(f"secret scan OK ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

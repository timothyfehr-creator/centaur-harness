"""Behavior tests for scripts/verify.py mode handling.

These invoke the real CLI via subprocess so they exercise exit codes exactly as
CI and the acceptance commands do. Paths are computed from this file's location,
so the tests pass regardless of the current working directory.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY = REPO_ROOT / "scripts" / "verify.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_scaffold_mode_exits_zero() -> None:
    result = _run("--mode", "scaffold")
    assert result.returncode == 0, result.stderr


def test_default_invocation_exits_zero_and_is_scaffold() -> None:
    result = _run()
    assert result.returncode == 0, result.stderr
    # The default invocation must behave like scaffold mode.
    assert "scaffold" in result.stdout.lower()


def test_unknown_mode_fails_clearly() -> None:
    result = _run("--mode", "definitely-not-a-real-mode")
    assert result.returncode != 0
    assert "unknown mode" in result.stderr.lower()


def test_draft_mode_not_implemented_yet() -> None:
    # WP-1 / WP0.1 must NOT implement draft mode; it should be rejected, not
    # silently treated as valid.
    result = _run("--mode", "draft")
    assert result.returncode != 0


def test_release_mode_never_falsely_passes() -> None:
    # Release mode must be unavailable / fail clearly until its gates exist.
    result = _run("--mode", "release")
    assert result.returncode != 0

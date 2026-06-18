"""Behavior tests for scripts/secret_scan.py.

Mirrors the subprocess convention in test_verify_modes.py: invoke the real CLI so
exit codes match CI and the acceptance commands. Paths are computed from this
file's location, so the tests pass regardless of the current working directory.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNER = REPO_ROOT / "scripts" / "secret_scan.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "secret_scan"


def _scan(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_safe_fixture_passes() -> None:
    result = _scan(str(FIXTURES / "safe"))
    assert result.returncode == 0, result.stderr


def test_unsafe_fixture_is_caught() -> None:
    result = _scan(str(FIXTURES / "unsafe"))
    assert result.returncode == 1, result.stdout
    # The report names the offending file.
    assert "leaked_credentials.txt" in result.stderr


def test_bare_repo_scan_passes() -> None:
    # No args -> tracked files minus the secret_scan fixtures. The repo must be
    # clean even though the (tracked) unsafe fixtures contain fake secrets.
    result = _scan()
    assert result.returncode == 0, result.stderr
    assert "secret scan OK" in result.stdout


def test_findings_are_redacted() -> None:
    # The full secret value must never appear in output (so CI logs do not leak);
    # only a masked prefix/suffix is shown.
    result = _scan(str(FIXTURES / "unsafe"))
    combined = result.stdout + result.stderr
    assert "AKIAIOSFODNN7EXAMPLE" not in combined
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in combined


# --- recall: one fake secret per rule family must be caught -----------------------
# NOTE: sample values must match our (deliberately permissive) regexes yet stay
# clearly SYNTHETIC -- the repo is on GitHub with push protection, which blocks
# real-looking provider keys (e.g. Stripe's documented example, live keys). Use
# test-mode / obviously-fake values so both scanners are satisfied.

_CAUGHT = {
    "aws": "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
    "github": "token=ghp_1234567890abcdefghijklmnopqrstuvwxyz",
    "google": 'key = "AIzaSyB1234567890abcdefghijklmnopqrstuv"',
    "stripe": "STRIPE=sk_test_FAKEstripekey0000000000",
    "anthropic": "key=sk-ant-api03-" + "a" * 40,
    "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----",
    "generic": 'api_key = "Hunter2RealLooking0xCAFEBABE"',
}

# --- precision: placeholders / env refs / prose must NOT be flagged ---------------

_IGNORED = {
    "placeholder": 'api_key = "your_api_key_here"',
    "env_ref": 'password = "${DB_PASSWORD}"',
    "os_environ": 'token = os.environ["CENTAUR_TOKEN"]',
    "prose": "the password policy requires rotation every ninety days",
    "short_value": 'api_key = "abc123"',
}


@pytest.mark.parametrize("name", sorted(_CAUGHT))
def test_known_secret_is_caught(tmp_path: Path, name: str) -> None:
    target = tmp_path / f"{name}.txt"
    target.write_text(_CAUGHT[name] + "\n")
    result = _scan(str(target))
    assert result.returncode == 1, f"{name} not caught; stderr={result.stderr!r}"


@pytest.mark.parametrize("name", sorted(_IGNORED))
def test_non_secret_is_ignored(tmp_path: Path, name: str) -> None:
    target = tmp_path / f"{name}.txt"
    target.write_text(_IGNORED[name] + "\n")
    result = _scan(str(target))
    assert result.returncode == 0, f"{name} false-positived; stderr={result.stderr!r}"


def test_allowlist_marker_skips_line(tmp_path: Path) -> None:
    target = tmp_path / "allowlisted.txt"
    target.write_text(
        "real=AKIAIOSFODNN7EXAMPLE\n"
        "doc=AKIAIOSFODNN7EXAMPLE  # pragma: allowlist secret\n"
    )
    result = _scan(str(target))
    # First line caught; the allowlisted line skipped -> exactly one finding.
    assert result.returncode == 1
    assert result.stderr.count("aws-access-key-id") == 1

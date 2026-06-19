"""Behavior tests for scripts/validate_sources.py (the source registry validator).

Mirrors the subprocess convention in test_schema_validation.py. Requires PyYAML.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_sources.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "registries"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_valid_sources_fixture_passes() -> None:
    result = _run(str(FIXTURES / "valid" / "sources_minimal.yaml"))
    assert result.returncode == 0, result.stderr


def test_factbase_sources_registry_validates() -> None:
    result = _run()  # bare -> factbase/sources.yaml
    assert result.returncode == 0, result.stderr
    assert "source validation OK" in result.stdout


# (fixture name, expected code, field/id token in the message)
_INVALID = {
    "sources_duplicate_id": ("duplicate-id", "src-001"),
    "sources_invalid_tier": ("invalid-enum", "tier"),
    "sources_missing_schema_version": ("missing-schema-version", "schema_version"),
}


@pytest.mark.parametrize("name,code,token", [(n, c, t) for n, (c, t) in sorted(_INVALID.items())])
def test_invalid_sources_fixture_single_fault(name: str, code: str, token: str) -> None:
    result = _run(str(FIXTURES / "invalid" / f"{name}.yaml"))
    assert result.returncode == 1, result.stdout
    findings = [ln for ln in result.stderr.splitlines() if ln.lstrip().startswith("- ")]
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0] and token in findings[0], f"{name}: {findings[0]!r}"


def test_fail_closed_on_missing_registry(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "nope.yaml"))
    assert result.returncode == 2

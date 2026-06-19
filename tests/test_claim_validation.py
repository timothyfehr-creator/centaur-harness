"""Behavior tests for scripts/validate_claims.py (the claim registry validator:
resolution to sources + the source-tier rule). Requires PyYAML.

Claim fixtures resolve against the *fixture* sources file (via --sources), so the
tests are isolated from factbase/sources.yaml.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_claims.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "registries"
SOURCES = FIXTURES / "valid" / "sources_minimal.yaml"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("name", ["claims_minimal", "claims_mixed_top_sources"])
def test_valid_claims_fixture_passes(name: str) -> None:
    # claims_mixed_top_sources proves a CONFIRMED claim with SOCIAL+OFFICIAL passes
    # (the tier rule does not over-block).
    result = _run(str(FIXTURES / "valid" / f"{name}.yaml"), "--sources", str(SOURCES))
    assert result.returncode == 0, result.stderr


def test_factbase_claims_resolve() -> None:
    result = _run()  # bare -> factbase/claims.yaml vs factbase/sources.yaml
    assert result.returncode == 0, result.stderr
    assert "claim validation OK" in result.stdout


# (fixture name, expected code, token in the message; "" = no token assertion)
_INVALID = {
    "claims_missing_id": ("missing-field", "id"),
    "claims_unresolved_source": ("unresolved-source-ref", "src-999"),
    "claims_multiple_unresolved_sources": ("unresolved-source-ref", "src-999"),
    "claims_no_sources": ("missing-source-ref", ""),
    "claims_duplicate_id": ("duplicate-id", "claim-001"),
    "claims_missing_schema_version": ("missing-schema-version", "schema_version"),
    "claims_top_confidence_social_only": ("confidence-tier-violation", "CONFIRMED"),
}


@pytest.mark.parametrize("name,code,token", [(n, c, t) for n, (c, t) in sorted(_INVALID.items())])
def test_invalid_claims_fixture_single_fault(name: str, code: str, token: str) -> None:
    result = _run(str(FIXTURES / "invalid" / f"{name}.yaml"), "--sources", str(SOURCES))
    assert result.returncode == 1, result.stdout
    findings = [ln for ln in result.stderr.splitlines() if ln.lstrip().startswith("- ")]
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0], f"{name}: {findings[0]!r}"
    if token:
        assert token in findings[0], f"{name}: {findings[0]!r}"


def test_fail_closed_on_missing_claims(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "nope.yaml"), "--sources", str(SOURCES))
    assert result.returncode == 2


def test_fail_closed_on_missing_sources(tmp_path: Path) -> None:
    result = _run(str(FIXTURES / "valid" / "claims_minimal.yaml"), "--sources", str(tmp_path / "nope.yaml"))
    assert result.returncode == 2

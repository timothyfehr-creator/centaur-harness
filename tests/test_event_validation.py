"""Behavior tests for scripts/validate_events.py (the event ledger validator:
resolution to claims). Requires PyYAML.

Event fixtures resolve against the *fixture* claims file (via --claims), isolating
the tests from factbase/claims.yaml.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_events.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "registries"
CLAIMS = FIXTURES / "valid" / "claims_minimal.yaml"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_valid_events_fixture_passes() -> None:
    result = _run(str(FIXTURES / "valid" / "events_minimal.yaml"), "--claims", str(CLAIMS))
    assert result.returncode == 0, result.stderr


def test_factbase_events_resolve() -> None:
    result = _run()  # bare -> factbase/events.yaml vs factbase/claims.yaml
    assert result.returncode == 0, result.stderr
    assert "event validation OK" in result.stdout


# (fixture name, expected code, token in the message; "" = no token assertion)
_INVALID = {
    "events_missing_claim_ref": ("missing-claim-ref", ""),
    "events_unresolved_claim": ("unresolved-claim-ref", "claim-999"),
    "events_multiple_unresolved": ("unresolved-claim-ref", "claim-999"),
    "events_duplicate_id": ("duplicate-id", "evt-001"),
    "events_invalid_category": ("invalid-enum", "category"),
    "events_invalid_confidence": ("invalid-enum", "confidence"),
    "events_missing_schema_version": ("missing-schema-version", "schema_version"),
}


@pytest.mark.parametrize("name,code,token", [(n, c, t) for n, (c, t) in sorted(_INVALID.items())])
def test_invalid_events_fixture_single_fault(name: str, code: str, token: str) -> None:
    result = _run(str(FIXTURES / "invalid" / f"{name}.yaml"), "--claims", str(CLAIMS))
    assert result.returncode == 1, result.stdout
    findings = [ln for ln in result.stderr.splitlines() if ln.lstrip().startswith("- ")]
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0], f"{name}: {findings[0]!r}"
    if token:
        assert token in findings[0], f"{name}: {findings[0]!r}"


def test_fail_closed_on_missing_events(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "nope.yaml"), "--claims", str(CLAIMS))
    assert result.returncode == 2


def test_fail_closed_on_broken_claims(tmp_path: Path) -> None:
    result = _run(str(FIXTURES / "valid" / "events_minimal.yaml"), "--claims", str(tmp_path / "nope.yaml"))
    assert result.returncode == 2

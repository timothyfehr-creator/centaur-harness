"""Behavior tests for scripts/validate_state.py (the source-or-label gate: a
REAL_WORLD_BASELINE state item must cite a resolving claim, or be relabeled).
Requires PyYAML.

State fixtures resolve against the *fixture* claims file (via --claims), isolating
the tests from factbase/claims.yaml.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_state.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "registries"
CLAIMS = FIXTURES / "valid" / "claims_minimal.yaml"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_valid_state_fixture_passes() -> None:
    # Mixed test artifact: a REAL_WORLD_BASELINE -> claim-001 (resolves) + an ASSUMPTION
    # item with no claims (must pass) + an ILLUSTRATIVE item.
    result = _run(str(FIXTURES / "valid" / "state_minimal.yaml"), "--claims", str(CLAIMS))
    assert result.returncode == 0, result.stderr


def test_example_initial_state_resolves() -> None:
    result = _run()  # bare -> the shipped example initial_state.yaml vs factbase/claims.yaml
    assert result.returncode == 0, result.stderr
    assert "state validation OK" in result.stdout


# (fixture name, expected code, token in the message; "" = no token assertion)
_INVALID = {
    "state_unlabeled_item": ("missing-field", "label"),
    "state_invalid_label": ("invalid-enum", "label"),
    "state_baseline_no_claims": ("unsupported-baseline", "REAL_WORLD_BASELINE"),
    "state_unresolved_claim": ("unresolved-claim-ref", "claim-999"),
    "state_duplicate_id": ("duplicate-id", "state-001"),
    "state_missing_schema_version": ("missing-schema-version", "schema_version"),
}


@pytest.mark.parametrize("name,code,token", [(n, c, t) for n, (c, t) in sorted(_INVALID.items())])
def test_invalid_state_fixture_single_fault(name: str, code: str, token: str) -> None:
    result = _run(str(FIXTURES / "invalid" / f"{name}.yaml"), "--claims", str(CLAIMS))
    assert result.returncode == 1, result.stdout
    findings = [ln for ln in result.stderr.splitlines() if ln.lstrip().startswith("- ")]
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0], f"{name}: {findings[0]!r}"
    if token:
        assert token in findings[0], f"{name}: {findings[0]!r}"


def test_fail_closed_on_missing_state(tmp_path: Path) -> None:
    result = _run(str(tmp_path / "nope.yaml"), "--claims", str(CLAIMS))
    assert result.returncode == 2


def test_fail_closed_on_broken_claims(tmp_path: Path) -> None:
    result = _run(str(FIXTURES / "valid" / "state_minimal.yaml"), "--claims", str(tmp_path / "nope.yaml"))
    assert result.returncode == 2


def test_fail_closed_on_empty_items(tmp_path: Path) -> None:
    # An empty items list is a refusal, not a clean pass.
    state = tmp_path / "empty.yaml"
    state.write_text('schema_version: "1.0"\nitems: []\n')
    result = _run(str(state), "--claims", str(CLAIMS))
    assert result.returncode == 2

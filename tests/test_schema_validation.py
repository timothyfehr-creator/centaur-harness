"""Behavior tests for scripts/validate_schemas.py (the scenario-schema gate).

Mirrors the subprocess convention in test_secret_scan.py. Requires PyYAML
(declared in requirements-dev.txt); the validator imports it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_schemas.py"
VERIFY = REPO_ROOT / "scripts" / "verify.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "schemas"
EXAMPLE = REPO_ROOT / "examples" / "ukraine_crimea_logistics" / "scenario.yaml"


def _validate(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "name",
    ["scenario_minimal", "scenario_update_mechanism", "scenario_sum_at_tolerance"],
)
def test_valid_fixture_passes(name: str) -> None:
    result = _validate(str(FIXTURES / "valid" / f"{name}.yaml"))
    assert result.returncode == 0, result.stderr


# Each invalid fixture is otherwise fully valid, so it must fail for EXACTLY this code
# (and only this code -- see the single-finding assertion below).
_INVALID = {
    "missing_schema_version": "missing-schema-version",
    "missing_branches": "missing-branches",
    "bad_probability_type": "probability-not-numeric",
    "probability_out_of_range": "probability-out-of-range",
    "probability_sum_out_of_range": "probability-sum-out-of-range",
    "too_few_signposts": "too-few-signposts",
    "missing_falsifier": "missing-falsifier",
    "missing_rationale": "missing-rationale-or-update",
    "malformed_yaml": "yaml-parse-error",
}


@pytest.mark.parametrize("name,code", sorted(_INVALID.items()))
def test_invalid_fixture_fails_for_expected_reason(name: str, code: str) -> None:
    result = _validate(str(FIXTURES / "invalid" / f"{name}.yaml"))
    assert result.returncode == 1, result.stdout
    # Findings print as "  - {code}  {where}  {msg}"; assert EXACTLY one, so a future
    # fixture edit can't silently introduce a second, unrelated failure.
    findings = [ln for ln in result.stderr.splitlines() if ln.lstrip().startswith("- ")]
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0], f"{name}: expected {code}; got {findings[0]!r}"


def test_real_example_passes() -> None:
    result = _validate(str(EXAMPLE))
    assert result.returncode == 0, result.stderr


def test_bare_run_validates_discovered_scenarios() -> None:
    result = _validate()
    assert result.returncode == 0, result.stderr
    assert "schema validation OK" in result.stdout


def test_fail_closed_on_empty_dir(tmp_path: Path) -> None:
    # A directory with no scenario.yaml must NOT report success (fail-closed).
    result = _validate(str(tmp_path))
    assert result.returncode == 2
    assert "no scenario files found" in result.stderr


def test_scaffold_validates_example_and_stays_green() -> None:
    # verify.py scaffold now structurally validates the (valid) example. Requires
    # PyYAML installed (declared dep); CI installs it.
    result = subprocess.run(
        [sys.executable, str(VERIFY), "--mode", "scaffold"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "scaffold verification OK" in result.stdout

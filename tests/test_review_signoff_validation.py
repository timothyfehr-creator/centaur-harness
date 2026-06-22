"""Behavior tests for scripts/validate_review_signoff.py (the WP8.1 attestation gate).

Single-fault fixtures live under tests/fixtures/attestations/. A `review_*` fixture is run
against the valid signoff (and `signoff_*` against the valid review), over the synthetic `scn/`
scenario dir whose run_ledger pins a FIXED-literal code_version -- so each invalid fixture
isolates exactly one code regardless of the live repo SHA. The real committed example
(examples/ukraine_crimea_logistics) is exercised read-only as the live "attestations current" guard.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_review_signoff.py"
FIX = REPO_ROOT / "tests" / "fixtures" / "attestations"
SCN, VALID, INVALID = FIX / "scn", FIX / "valid", FIX / "invalid"
EXAMPLE = REPO_ROOT / "examples" / "ukraine_crimea_logistics"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(VALIDATOR), *args],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def _fixtures(review: Path, signoff: Path) -> subprocess.CompletedProcess[str]:
    return _run("--scenario-dir", str(SCN), "--review", str(review), "--signoff", str(signoff))


def _findings(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.lstrip().startswith("- ")]


# --- the committed example (the live "attestations match the ledger" guard) ----------

def test_committed_example_attests() -> None:
    result = _run()  # bare -> examples/ukraine_crimea_logistics/{review,signoff,run_ledger,scenario}
    assert result.returncode == 0, result.stderr
    assert "review/signoff validation OK" in result.stdout


def test_committed_example_is_secret_scan_clean() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"),
         str(EXAMPLE / "review.yaml"), str(EXAMPLE / "signoff.yaml")],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_valid_fixtures_attest() -> None:
    result = _fixtures(VALID / "review.yaml", VALID / "signoff.yaml")
    assert result.returncode == 0, result.stderr


# --- single-fault (review_* run vs the valid signoff; signoff_* vs the valid review) ----

# name -> (code, distinguishing token in the finding line)
_INVALID = {
    "review_missing_schema_version": ("missing-schema-version", "schema_version"),
    "review_missing_target": ("missing-field", "target"),
    "review_missing_verdict": ("missing-field", "verdict"),
    "review_invalid_verdict": ("invalid-enum", "verdict"),
    "review_empty_findings": ("empty-findings", "findings"),
    "review_unresolved_scenario": ("unresolved-scenario-ref", "'scn'"),
    "review_stale": ("stale-attestation", "review code_version"),
    "review_revise": ("revise-verdict", "REVISE"),
    "signoff_missing_schema_version": ("missing-schema-version", "schema_version"),
    "signoff_missing_review_ref": ("missing-field", "review_ref"),
    "signoff_missing_decision": ("missing-field", "decision"),
    "signoff_invalid_decision": ("invalid-enum", "decision"),
    "signoff_missing_calibration": ("missing-field", "calibration_status"),
    "signoff_invalid_calibration": ("invalid-enum", "calibration_status"),
    "signoff_bad_date": ("invalid-format", "date"),
    "signoff_unresolved_review_ref": ("unresolved-review-ref", "review-999"),
    "signoff_stale": ("stale-attestation", "signoff code_version"),
    "signoff_rejected": ("rejected-decision", "REJECTED"),
}


@pytest.mark.parametrize("name,code,token", [(n, c, t) for n, (c, t) in sorted(_INVALID.items())])
def test_invalid_fixture_single_fault(name: str, code: str, token: str) -> None:
    if name.startswith("review_"):
        result = _fixtures(INVALID / f"{name}.yaml", VALID / "signoff.yaml")
    else:
        result = _fixtures(VALID / "review.yaml", INVALID / f"{name}.yaml")
    assert result.returncode == 1, result.stdout
    findings = _findings(result.stderr)
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0] and token in findings[0], f"{name}: {findings[0]!r}"


# --- fail-closed (exit 2): never report clean on nothing ------------------------------

def test_fail_closed_on_empty_attestation() -> None:
    assert _fixtures(INVALID / "empty_doc.yaml", VALID / "signoff.yaml").returncode == 2


def test_fail_closed_on_missing_review(tmp_path: Path) -> None:
    assert _fixtures(tmp_path / "nope.yaml", VALID / "signoff.yaml").returncode == 2


def test_fail_closed_on_missing_signoff(tmp_path: Path) -> None:
    assert _fixtures(VALID / "review.yaml", tmp_path / "nope.yaml").returncode == 2


def test_fail_closed_on_broken_ledger(tmp_path: Path) -> None:
    scn = tmp_path / "scn"
    scn.mkdir()
    (scn / "scenario.yaml").write_text("schema_version: '1.0'\n")
    (scn / "run_ledger.yaml").write_text("not-a-mapping\n")  # no code_version -> can't bind
    (scn / "review.yaml").write_text((VALID / "review.yaml").read_text())
    (scn / "signoff.yaml").write_text((VALID / "signoff.yaml").read_text())
    assert _run("--scenario-dir", str(scn)).returncode == 2


def test_fail_closed_on_missing_scenario(tmp_path: Path) -> None:
    scn = tmp_path / "scn"
    scn.mkdir()
    (scn / "run_ledger.yaml").write_text("code_version: 'x'\n")  # no scenario.yaml -> nothing to attest
    (scn / "review.yaml").write_text((VALID / "review.yaml").read_text())
    (scn / "signoff.yaml").write_text((VALID / "signoff.yaml").read_text())
    assert _run("--scenario-dir", str(scn)).returncode == 2

"""Behavior tests for scripts/validate_calibration.py (the WP9.1 evidence-or-label gate).

The CALIBRATED path is exercised ENTIRELY via fixtures (the committed ukraine example stays
ILLUSTRATIVE, so its run_ledger lockfile never moves). Fixtures live under
tests/fixtures/calibrations/: a synthetic scn/ scenario dir (a fixed-literal run_ledger
code_version + a CALIBRATED signoff) so each invalid record isolates exactly one code.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_calibration.py"
FIX = REPO_ROOT / "tests" / "fixtures" / "calibrations"
SCN, VALID, INVALID = FIX / "scn", FIX / "valid", FIX / "invalid"
ILLUSTRATIVE_SIGNOFF = SCN / "signoff_illustrative.yaml"
EXAMPLE = REPO_ROOT / "examples" / "ukraine_crimea_logistics"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(VALIDATOR), *args],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def _findings(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.lstrip().startswith("- ")]


# --- the committed ukraine example (ILLUSTRATIVE -> no record required) ----------------

def test_committed_example_needs_no_record() -> None:
    result = _run()  # bare -> examples/ukraine_crimea_logistics (signoff is ILLUSTRATIVE)
    assert result.returncode == 0, result.stderr
    assert "ILLUSTRATIVE" in result.stdout and "no record required" in result.stdout


def test_ukraine_signoff_status_is_illustrative() -> None:
    # The lockfile guard: ukraine must NOT become CALIBRATED (that would require a record file
    # and move the run_ledger). WP9 keeps the example ILLUSTRATIVE.
    doc = yaml.safe_load((EXAMPLE / "signoff.yaml").read_text())
    assert doc["calibration_status"] == "ILLUSTRATIVE"


def test_ukraine_has_no_calibration_yaml() -> None:
    assert not (EXAMPLE / "calibration.yaml").exists()


# --- the valid CALIBRATED path (fixtures only) -----------------------------------------

def test_valid_calibrated_record() -> None:
    result = _run("--scenario-dir", str(SCN), "--calibration", str(VALID / "calibration.yaml"))
    assert result.returncode == 0, result.stderr
    assert "CALIBRATED" in result.stdout and "BRIER_SCORE" in result.stdout


def test_brier_boundary_values_pass(tmp_path: Path) -> None:
    base = (VALID / "calibration.yaml").read_text()
    for mv in ("0.0", "1.0"):
        rec = tmp_path / f"cal_{mv}.yaml"
        rec.write_text(base.replace("metric_value: 0.218", f"metric_value: {mv}"))
        result = _run("--scenario-dir", str(SCN), "--calibration", str(rec))
        assert result.returncode == 0, f"mv={mv}: {result.stderr}"


# --- evidence-or-label (§5) cross-gate cases -------------------------------------------

def test_calibrated_without_record_is_unsupported() -> None:
    # CALIBRATED signoff (scn default) + no calibration.yaml -> a content finding (blocks release).
    result = _run("--scenario-dir", str(SCN))  # scn has no calibration.yaml
    assert result.returncode == 1
    findings = _findings(result.stderr)
    assert len(findings) == 1 and "unsupported-calibration" in findings[0]


def test_illustrative_without_record_passes() -> None:
    result = _run("--scenario-dir", str(SCN), "--signoff", str(ILLUSTRATIVE_SIGNOFF))
    assert result.returncode == 0, result.stderr


def test_illustrative_with_record_is_inconsistent() -> None:
    result = _run("--scenario-dir", str(SCN), "--signoff", str(ILLUSTRATIVE_SIGNOFF),
                  "--calibration", str(VALID / "calibration.yaml"))
    assert result.returncode == 1
    findings = _findings(result.stderr)
    assert len(findings) == 1 and "consistency-note" in findings[0]


# --- single-fault (each invalid record -> exactly one code) ----------------------------

# name -> (code, distinguishing token in the finding line)
_INVALID = {
    "cal_missing_schema_version": ("missing-schema-version", "schema_version"),
    "cal_missing_outcome_authority": ("missing-field", "outcome_authority"),
    "cal_invalid_metric": ("invalid-enum", "metric"),
    "cal_metric_value_not_numeric": ("wrong-type", "metric_value"),
    "cal_metric_value_bool": ("wrong-type", "metric_value"),
    "cal_metric_value_nan": ("wrong-type", "metric_value"),
    "cal_metric_value_inf": ("wrong-type", "metric_value"),
    "cal_metric_value_brier_out_of_range": ("invalid-range", "metric_value"),
    "cal_log_loss_negative": ("invalid-range", "metric_value"),
    "cal_outcome_count_not_int": ("wrong-type", "outcome_count"),
    "cal_outcome_count_bool": ("wrong-type", "outcome_count"),
    "cal_outcome_count_zero": ("invalid-range", "outcome_count"),
    "cal_bad_scoring_date": ("invalid-format", "scoring_date"),
    "cal_baseline_out_of_range": ("invalid-range", "baseline_value"),
    "cal_unresolved_target": ("unresolved-scenario-ref", "some-other-scenario"),
    "cal_stale_code_version": ("stale-calibration", "calibration code_version"),
}


@pytest.mark.parametrize("name,code,token", [(n, c, t) for n, (c, t) in sorted(_INVALID.items())])
def test_invalid_record_single_fault(name: str, code: str, token: str) -> None:
    result = _run("--scenario-dir", str(SCN), "--calibration", str(INVALID / f"{name}.yaml"))
    assert result.returncode == 1, result.stdout
    findings = _findings(result.stderr)
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0] and token in findings[0], f"{name}: {findings[0]!r}"


# --- fail-closed (exit 2) --------------------------------------------------------------

def test_fail_closed_on_unparseable_record(tmp_path: Path) -> None:
    # CALIBRATED signoff + a present-but-unparseable record -> fail-closed, not a soft finding.
    bad = tmp_path / "bad.yaml"
    bad.write_text("metric_value: [unterminated\n")
    assert _run("--scenario-dir", str(SCN), "--calibration", str(bad)).returncode == 2


def test_fail_closed_on_missing_scenario(tmp_path: Path) -> None:
    scn = tmp_path / "scn"
    scn.mkdir()
    (scn / "run_ledger.yaml").write_text("code_version: 'x'\n")
    (scn / "signoff.yaml").write_text("calibration_status: ILLUSTRATIVE\n")
    assert _run("--scenario-dir", str(scn)).returncode == 2  # no scenario.yaml


def test_fail_closed_on_broken_ledger(tmp_path: Path) -> None:
    scn = tmp_path / "scn"
    scn.mkdir()
    (scn / "scenario.yaml").write_text("schema_version: '1.0'\n")
    (scn / "run_ledger.yaml").write_text("not-a-mapping\n")  # no code_version
    (scn / "signoff.yaml").write_text("calibration_status: ILLUSTRATIVE\n")
    assert _run("--scenario-dir", str(scn)).returncode == 2

"""Behavior tests for scripts/validate_calibration_feasibility.py (the WP-E2c feasibility gate).

The gate is independent of validate_calibration.py: a feasibility record lives at a distinct filename,
keeps calibration_status UNCALIBRATED, and the verdict enum has no 'feasible' value. Fixtures live under
tests/fixtures/calibration_feasibility/: a synthetic scn/ scenario (fixed-literal run_ledger code_version
+ an UNCALIBRATED signoff, plus a CALIBRATED one for the contradictory-status case) and a valid record;
single-fault invalids are derived by dict-mutating the valid record (one targeted change each).
"""
from __future__ import annotations

import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "validate_calibration_feasibility.py"
CAL_GATE = REPO_ROOT / "scripts" / "validate_calibration.py"
FIX = REPO_ROOT / "tests" / "fixtures" / "calibration_feasibility"
SCN, VALID = FIX / "scn", FIX / "valid" / "calibration_feasibility.yaml"
CALIBRATED_SIGNOFF = SCN / "signoff_calibrated.yaml"
BASE = yaml.safe_load(VALID.read_text())


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(GATE), *args], cwd=REPO_ROOT, capture_output=True, text=True)


def _findings(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.lstrip().startswith("- ")]


# --- the valid record + glob mode -------------------------------------------------------

def test_valid_record_passes() -> None:
    result = _run("--scenario-dir", str(SCN), "--feasibility", str(VALID))
    assert result.returncode == 0, result.stderr
    assert "NOT_FEASIBLE" in result.stdout


def test_glob_mode_passes() -> None:
    # bare invocation globs examples/*/calibration_feasibility.yaml -> vacuous pass when none exist,
    # validates the het record once E2c-2 lands it. Either way: clean (exit 0).
    result = _run()
    assert result.returncode == 0, result.stderr


# --- the central non-regression: the feasibility file is INVISIBLE to the calibration gate ----

def test_feasibility_record_does_not_trip_the_calibration_gate(tmp_path: Path) -> None:
    d = tmp_path / "scn"
    d.mkdir()
    for f in ("scenario.yaml", "run_ledger.yaml", "signoff.yaml"):   # signoff is UNCALIBRATED
        shutil.copy(SCN / f, d / f)
    shutil.copy(VALID, d / "calibration_feasibility.yaml")            # present, but NO calibration.yaml
    r = subprocess.run([sys.executable, str(CAL_GATE), "--scenario-dir", str(d)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "no record required" in r.stdout, r.stderr


def test_ukraine_has_no_feasibility_record() -> None:
    assert not (REPO_ROOT / "examples" / "ukraine_crimea_logistics" / "calibration_feasibility.yaml").exists()


# --- contradictory status: a 'cannot calibrate' record under a CALIBRATED signoff -------

def test_contradictory_status_under_calibrated_signoff() -> None:
    result = _run("--scenario-dir", str(SCN), "--feasibility", str(VALID), "--signoff", str(CALIBRATED_SIGNOFF))
    assert result.returncode == 1
    findings = _findings(result.stderr)
    assert len(findings) == 1 and "contradictory-status" in findings[0]


# --- single-fault (each invalid record -> exactly one code), derived from the valid base ----

_MUTATIONS = [
    ("missing_schema_version", lambda d: d.pop("schema_version"), "missing-schema-version", "schema_version"),
    ("missing_attempted_observable", lambda d: d.pop("attempted_observable"), "missing-field", "attempted_observable"),
    ("invalid_verdict", lambda d: d.__setitem__("verdict", "FEASIBLE"), "invalid-enum", "verdict"),
    ("empty_reasons", lambda d: d.__setitem__("binding_reasons", []), "empty-reasons", "binding_reasons"),
    ("bad_feasibility_date", lambda d: d.__setitem__("feasibility_date", "2026/06/23"), "invalid-format", "feasibility_date"),
    # WP-E2c.1 #6: unknown-key rejection is the structural boundary -- a smuggled comparison/ground-truth
    # field cannot ride along, and the retired descriptive_band shape (model_value_pct) is now an unknown key.
    ("unknown_top_key", lambda d: d.__setitem__("matches_ground_truth", True), "unknown-key", "matches_ground_truth"),
    ("readd_model_value_pct", lambda d: d["external_context"].__setitem__("model_value_pct", 80), "unknown-key", "model_value_pct"),
    # machine-readable honesty enums: each pinned to its sole honest value (the teeth), + presence required.
    ("missing_comparison_role", lambda d: d["external_context"].pop("comparison_role"), "missing-field", "comparison_role"),
    ("bad_comparison_role", lambda d: d["external_context"].__setitem__("comparison_role", "VALIDATION"), "invalid-enum", "comparison_role"),
    ("bad_calibration_effect", lambda d: d["external_context"].__setitem__("calibration_effect", "MOVES_P"), "invalid-enum", "calibration_effect"),
    # type + range on the numeric fields.
    ("range_unordered", lambda d: d["external_context"].__setitem__("observed_range_pct", [77, 46]), "out-of-range", "observed_range_pct"),
    ("weeks_out_of_range", lambda d: d["external_context"].__setitem__("weeks_computed", 99), "out-of-range", "weeks_computed"),
    ("unlabeled_band", lambda d: d["external_context"].__setitem__("labels", []), "unlabeled-band", "labels"),
    ("bad_source_class", lambda d: d["external_context"].__setitem__("source_class", "BOGUS"), "invalid-enum", "source_class"),
    # clause-aware over-claim scan over the WHOLE doc: an affirmation in any allowed free-text string is caught.
    ("overclaim_caveat", lambda d: d["external_context"].__setitem__("caveat", "this channel is calibrated against the data"), "over-claim-language", "calibrated"),
    ("overclaim_in_binding_reason", lambda d: d["binding_reasons"].append("fully calibrated and independently verified"), "over-claim-language", "calibrated"),
    ("overclaim_in_ldc_note", lambda d: d["launch_denominator_conflict"].__setitem__("note", "validated against ground truth"), "over-claim-language", "validated"),
    ("sha_pinned_but_null", lambda d: d["provenance"][0].__setitem__("sha256_status", "PINNED"), "invalid-format", "sha256"),
    ("sha_blocked_but_hash", lambda d: d["provenance"][0].__setitem__("sha256", "a" * 64), "provenance-contradiction", "sha256"),
    ("unknown_provenance_key", lambda d: d["provenance"][0].__setitem__("matches", "ground-truth"), "unknown-key", "matches"),
    ("unresolved_target", lambda d: d.__setitem__("target", "some-other-scenario"), "unresolved-scenario-ref", "some-other-scenario"),
    ("stale_code_version", lambda d: d.__setitem__("code_version", "f" * 40), "stale-feasibility", "feasibility code_version"),
]


@pytest.mark.parametrize("name,mutate,code,token", _MUTATIONS, ids=[m[0] for m in _MUTATIONS])
def test_single_fault_invalid(name, mutate, code, token, tmp_path: Path) -> None:
    doc = copy.deepcopy(BASE)
    mutate(doc)
    rec = tmp_path / "calibration_feasibility.yaml"
    rec.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    result = _run("--scenario-dir", str(SCN), "--feasibility", str(rec))
    assert result.returncode == 1, f"{name}: expected findings; stdout={result.stdout}"
    findings = _findings(result.stderr)
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0] and token in findings[0], f"{name}: {findings[0]!r}"


# --- the over-claim scan is CLAUSE-AWARE: honest negated disclaimers pass -----------------

@pytest.mark.parametrize("caveat", [
    "background context only; this is not calibrated and was never validated or corroborated",
    "single-source self-report; no independent estimate corroborated it",
    "a plausibility check, not a fit and not validated against any ground truth",
])
def test_negated_disclaimer_passes(caveat: str, tmp_path: Path) -> None:
    # A negator earlier in the same clause exempts the flagged word -- the honest disclaimer must NOT trip.
    doc = copy.deepcopy(BASE)
    doc["external_context"]["caveat"] = caveat
    rec = tmp_path / "calibration_feasibility.yaml"
    rec.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    result = _run("--scenario-dir", str(SCN), "--feasibility", str(rec))
    assert result.returncode == 0, f"honest disclaimer wrongly blocked: {result.stderr}"


def test_overclaim_after_negation_in_later_clause_fails(tmp_path: Path) -> None:
    # clause-aware, not a global lookbehind: "not calibrated BUT validated" must FAIL on the second clause.
    doc = copy.deepcopy(BASE)
    doc["external_context"]["caveat"] = "not calibrated, but fully validated against the data"
    rec = tmp_path / "calibration_feasibility.yaml"
    rec.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    result = _run("--scenario-dir", str(SCN), "--feasibility", str(rec))
    assert result.returncode == 1
    assert "over-claim-language" in result.stderr and "validated" in result.stderr


# --- the committed het record passes the hardened gate ------------------------------------

def test_committed_het_record_passes_hardened_gate() -> None:
    het = REPO_ROOT / "examples" / "ru_ua_salvo_heterogeneous"
    result = _run("--scenario-dir", str(het))
    assert result.returncode == 0, result.stderr
    assert "NOT_FEASIBLE" in result.stdout


# --- fail-closed (exit 2) ---------------------------------------------------------------

def test_fail_closed_on_unparseable_record(tmp_path: Path) -> None:
    bad = tmp_path / "calibration_feasibility.yaml"
    bad.write_text("verdict: [unterminated\n")
    assert _run("--scenario-dir", str(SCN), "--feasibility", str(bad)).returncode == 2


def test_fail_closed_when_record_absent_in_scenario_dir_mode(tmp_path: Path) -> None:
    # --scenario-dir mode asked to validate a record that isn't there -> fail-closed, not a silent pass.
    assert _run("--scenario-dir", str(tmp_path)).returncode == 2


def test_fail_closed_on_missing_signoff(tmp_path: Path) -> None:
    d = tmp_path / "scn"
    d.mkdir()
    shutil.copy(SCN / "scenario.yaml", d / "scenario.yaml")
    shutil.copy(SCN / "run_ledger.yaml", d / "run_ledger.yaml")
    shutil.copy(VALID, d / "calibration_feasibility.yaml")           # record present, but NO signoff
    assert _run("--scenario-dir", str(d)).returncode == 2

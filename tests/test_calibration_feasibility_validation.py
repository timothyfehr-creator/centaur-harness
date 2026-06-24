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

import validate_calibration_feasibility as vcf  # noqa: E402


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
    # WP-E2c.1 #7-min: the dossier is external, so a hash exists iff PINNED (never fabricated).
    ("dossier_pinned_but_null", lambda d: d.__setitem__("dossier_sha256_status", "PINNED"), "invalid-format", "dossier_sha256"),
    ("dossier_hash_under_external", lambda d: d.__setitem__("dossier_sha256", "a" * 64), "dossier-contradiction", "dossier_sha256"),
    # WP-E2c.1 C2.1 (adversarial-verify fix): an allowed SCALAR key cannot carry a nested object smuggling a
    # comparison (the unknown-key check alone only inspects keys, not value shape).
    ("smuggle_in_ldc_note", lambda d: d["launch_denominator_conflict"].__setitem__("note", {"matches_ground_truth": True}), "non-scalar-value", "note"),
    ("smuggle_in_prov_version", lambda d: d["provenance"][0].__setitem__("version", {"matches_ground_truth": True}), "non-scalar-value", "version"),
    ("smuggle_in_ldc_value_source", lambda d: d["launch_denominator_conflict"]["values"][0].__setitem__("source", {"model_p": 62}), "incomplete-denominator-value", "source"),
    # DIRECT comparability is gone: a directly-comparable band IS a calibration target, contradicting CONTEXT_ONLY.
    ("direct_comparability", lambda d: d["external_context"].__setitem__("comparability_to_model_p", "DIRECT"), "invalid-enum", "comparability_to_model_p"),
    # independent-review fix: a denominator-conflict value must carry usable evidence (an empty {} can't).
    ("incomplete_denominator_value", lambda d: d["launch_denominator_conflict"].__setitem__("values", [{}]), "incomplete-denominator-value", "values[0]"),
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


@pytest.mark.parametrize("caveat,word", [
    # C2.1 fail-OPEN fix: a far/unrelated leading negator must NOT exempt a later affirmation.
    ("there is no question that the model was validated against ground truth", "validated"),
    ("background context; aside from no caveats, the band is fully calibrated", "calibrated"),
    # C2.1 NFKC: a full-width-Unicode spelling of a flagged word is normalized then caught.
    ("the model is fully ｖａｌｉｄａｔｅｄ to the data", "validated"),
])
def test_overclaim_evasions_now_caught(caveat: str, word: str, tmp_path: Path) -> None:
    doc = copy.deepcopy(BASE)
    doc["external_context"]["caveat"] = caveat
    rec = tmp_path / "calibration_feasibility.yaml"
    rec.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    result = _run("--scenario-dir", str(SCN), "--feasibility", str(rec))
    assert result.returncode == 1, f"evasion not caught: {result.stdout}"
    assert "over-claim-language" in result.stderr


def test_dict_in_labels_fails_gracefully_no_crash(tmp_path: Path) -> None:
    # C2.1 robustness: a dict item in labels (would crash set(labels)) is a graceful finding, not a traceback,
    # and does not ride along even when a valid marker is also present.
    doc = copy.deepcopy(BASE)
    doc["external_context"]["labels"] = ["SINGLE_SOURCE", {"matches_ground_truth": True}]
    rec = tmp_path / "calibration_feasibility.yaml"
    rec.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    result = _run("--scenario-dir", str(SCN), "--feasibility", str(rec))
    assert result.returncode == 1, result.stdout                 # a finding, NOT a crash (which would be rc 1 w/ traceback or rc !=1)
    assert "unlabeled-band" in result.stderr
    assert "Traceback" not in result.stderr


# --- independent-review fix: the release sweep is RECURSIVE (a nested scenario can't be skipped) -----

def test_sweep_dirs_finds_nested_scenario(tmp_path: Path) -> None:
    # the bug an independent review caught: verify.py covers examples/**/ but the feasibility sweep used
    # examples/*/, so a nested NOT_FEASIBLE scenario with a missing record was attestation-covered yet
    # feasibility-skipped. _sweep_dirs must glob recursively, and its dir-set must be a true SUPERSET of
    # verify.py's attestation coverage (review-OR-signoff) -- including a review-ONLY dir (round-2 review).
    import verify  # noqa: E402  (scripts/ is on sys.path via pyproject pythonpath)
    ex = tmp_path / "examples"
    (ex / "flat").mkdir(parents=True)
    (ex / "flat" / "signoff.yaml").write_text("schema_version: '1.0'\n")
    (ex / "nested" / "scn").mkdir(parents=True)
    (ex / "nested" / "scn" / "signoff.yaml").write_text("schema_version: '1.0'\n")
    (ex / "deep" / "a" / "b").mkdir(parents=True)
    (ex / "deep" / "a" / "b" / "calibration_feasibility.yaml").write_text("schema_version: '1.0'\n")
    (ex / "reviewonly").mkdir(parents=True)
    (ex / "reviewonly" / "review.yaml").write_text("schema_version: '1.0'\n")   # review-only: in coverage, must be swept
    found = set(vcf._sweep_dirs(ex))
    assert ex / "flat" in found
    assert ex / "nested" / "scn" in found            # the previously-skipped nested case
    assert ex / "deep" / "a" / "b" in found           # record-bearing at depth, also covered
    assert ex / "reviewonly" in found                 # review-only dir (round-2: was omitted before)
    # the actual invariant: the feasibility sweep is a SUPERSET of verify.py's attestation coverage set,
    # so nothing attestation-covered can be feasibility-skipped (tmp_path is the repo_root verify globs under).
    attested = set(verify._attested_scenario_dirs(tmp_path))
    assert attested <= found, f"attestation-covered dirs NOT in the feasibility sweep: {attested - found}"


# --- the committed het record passes the hardened gate ------------------------------------

def test_committed_het_record_passes_hardened_gate() -> None:
    het = REPO_ROOT / "examples" / "ru_ua_salvo_heterogeneous"
    result = _run("--scenario-dir", str(het))
    assert result.returncode == 0, result.stderr
    assert "NOT_FEASIBLE" in result.stdout


# --- WP-E2c.1 #2: the signoff DECLARES the disposition + is BOUND to the record bytes -------
# (binding runs in disposition-driven mode -- `--scenario-dir` with NO `--feasibility` override)

import hashlib  # noqa: E402


def _bind_scn(tmp_path: Path, *, disposition: str, ref: str = "calfeas-001",
              record: bool = True, record_mut=None, sha: str | None = None) -> Path:
    """A synthetic scn/ dir: SCN's scenario + ledger, a signoff DECLARING `disposition` (+ ref/sha bound to
    the record's bytes when sha is None), and optionally the record itself. Returns the dir to validate."""
    d = tmp_path / "scn"
    d.mkdir()
    shutil.copy(SCN / "scenario.yaml", d / "scenario.yaml")
    shutil.copy(SCN / "run_ledger.yaml", d / "run_ledger.yaml")
    rec_sha = None
    if record:
        doc = copy.deepcopy(BASE)
        if record_mut:
            record_mut(doc)
        body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode()
        (d / "calibration_feasibility.yaml").write_bytes(body)
        rec_sha = hashlib.sha256(body).hexdigest()
    signoff = {"schema_version": "1.0", "calibration_status": "UNCALIBRATED",
               "calibration_disposition": disposition}
    if disposition in ("NOT_FEASIBLE", "INSUFFICIENT_DATA"):
        signoff["calibration_feasibility_ref"] = ref
        signoff["calibration_feasibility_sha256"] = sha if sha is not None else (rec_sha or "0" * 64)
    (d / "signoff.yaml").write_text(yaml.safe_dump(signoff, sort_keys=False))
    return d


def test_binding_passes_when_record_matches(tmp_path: Path) -> None:
    assert _run("--scenario-dir", str(_bind_scn(tmp_path, disposition="NOT_FEASIBLE"))).returncode == 0


def test_missing_feasibility_record(tmp_path: Path) -> None:
    # disposition says a record exists, but it does NOT -- the "say-so" must be backed (#2 keystone).
    d = _bind_scn(tmp_path, disposition="NOT_FEASIBLE", record=False)
    r = _run("--scenario-dir", str(d))
    assert r.returncode == 1 and "missing-feasibility-record" in r.stderr


def test_stale_binding_when_record_edited_without_resign(tmp_path: Path) -> None:
    # the signed sha no longer matches the record bytes -> editing without re-signing fails closed.
    d = _bind_scn(tmp_path, disposition="NOT_FEASIBLE", sha="0" * 64)
    r = _run("--scenario-dir", str(d))
    assert r.returncode == 1 and "stale-feasibility-binding" in r.stderr


def test_disposition_mismatch_verdict(tmp_path: Path) -> None:
    # the record's verdict (NOT_FEASIBLE) must equal the declared disposition (INSUFFICIENT_DATA here).
    d = _bind_scn(tmp_path, disposition="INSUFFICIENT_DATA", ref="calfeas-001")
    r = _run("--scenario-dir", str(d))
    assert r.returncode == 1 and "disposition-mismatch" in r.stderr


def test_unresolved_feasibility_ref(tmp_path: Path) -> None:
    d = _bind_scn(tmp_path, disposition="NOT_FEASIBLE", ref="wrong-id")
    r = _run("--scenario-dir", str(d))
    assert r.returncode == 1 and "unresolved-feasibility-ref" in r.stderr


def test_record_present_under_none_disposition(tmp_path: Path) -> None:
    # a record exists but the signoff disposes NONE -- a record obliges a feasibility verdict.
    d = _bind_scn(tmp_path, disposition="NONE")
    r = _run("--scenario-dir", str(d))
    assert r.returncode == 1 and "disposition-mismatch" in r.stderr


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

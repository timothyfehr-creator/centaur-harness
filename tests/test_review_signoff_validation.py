"""Behavior tests for scripts/validate_review_signoff.py (the WP8.1 attestation gate, WP-E2c.1 model).

Single-fault invalids are derived by dict-mutating the valid review + signoff (one targeted change each),
run over the synthetic `scn/` scenario dir whose run_ledger pins a FIXED-literal code_version -- so each
isolates exactly one code regardless of the live repo SHA. The real committed example
(examples/ukraine_crimea_logistics) is exercised read-only as the live "attestations current" guard.
attestation_kind (WP-E2c.1) partitions the legal verdict/decision so a SYNTHETIC self-check can never spell
ACCEPT/APPROVED.
"""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_review_signoff.py"
FIX = REPO_ROOT / "tests" / "fixtures" / "attestations"
SCN, VALID, INVALID = FIX / "scn", FIX / "valid", FIX / "invalid"
REVIEWERS = FIX / "reviewers.yaml"   # allow-lists the valid INDEPENDENT fixtures' reviewer/signer
EXAMPLE = REPO_ROOT / "examples" / "ukraine_crimea_logistics"
REVIEW_BASE = yaml.safe_load((VALID / "review.yaml").read_text())     # valid INDEPENDENT + ACCEPT
SIGNOFF_BASE = yaml.safe_load((VALID / "signoff.yaml").read_text())   # valid INDEPENDENT + APPROVED


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(VALIDATOR), *args],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def _run_pair(tmp_path: Path, review: dict, signoff: dict) -> subprocess.CompletedProcess[str]:
    r, s = tmp_path / "review.yaml", tmp_path / "signoff.yaml"
    r.write_text(yaml.safe_dump(review, sort_keys=False, allow_unicode=True))
    s.write_text(yaml.safe_dump(signoff, sort_keys=False, allow_unicode=True))
    return _run("--scenario-dir", str(SCN), "--review", str(r), "--signoff", str(s),
                "--reviewers", str(REVIEWERS))


def _findings(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.lstrip().startswith("- ")]


# --- the committed example (the live "attestations match the ledger" guard) ----------

def test_committed_example_attests() -> None:
    result = _run()  # bare -> examples/ukraine_crimea_logistics
    assert result.returncode == 0, result.stderr
    assert "review/signoff validation OK" in result.stdout


def test_committed_example_is_secret_scan_clean() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"),
         str(EXAMPLE / "review.yaml"), str(EXAMPLE / "signoff.yaml")],
        cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- valid paths: INDEPENDENT + ACCEPT/APPROVED, and SYNTHETIC_SELF_CHECK + passing -----

def test_valid_independent_attests(tmp_path: Path) -> None:
    assert _run_pair(tmp_path, copy.deepcopy(REVIEW_BASE), copy.deepcopy(SIGNOFF_BASE)).returncode == 0


def test_valid_synthetic_self_check_attests(tmp_path: Path) -> None:
    # a self-check CANNOT spell ACCEPT/APPROVED, but a well-formed self-check passes (exit 0).
    r, s = copy.deepcopy(REVIEW_BASE), copy.deepcopy(SIGNOFF_BASE)
    r.update(attestation_kind="SYNTHETIC_SELF_CHECK", verdict="SELF_CHECK_PASSED",
             reviewer="synthetic self-check")
    s.update(attestation_kind="SYNTHETIC_SELF_CHECK", decision="EXTERNAL_REVIEW_PENDING",
             signed_by="harness self-check")
    assert _run_pair(tmp_path, r, s).returncode == 0


# --- single-fault (one mutation -> exactly one code). mutate fn takes (review, signoff). ----

def _r(fn):  # mutate review only
    return lambda r, s: fn(r)


def _s(fn):  # mutate signoff only
    return lambda r, s: fn(s)


_MUTATIONS = [
    ("review_missing_schema_version", _r(lambda d: d.pop("schema_version")), "missing-schema-version", "schema_version"),
    ("review_missing_target", _r(lambda d: d.pop("target")), "missing-field", "target"),
    ("review_missing_kind", _r(lambda d: d.pop("attestation_kind")), "missing-field", "attestation_kind"),
    ("review_invalid_kind", _r(lambda d: d.__setitem__("attestation_kind", "BOGUS")), "invalid-enum", "attestation_kind"),
    ("review_invalid_verdict", _r(lambda d: d.__setitem__("verdict", "MAYBE")), "invalid-enum", "verdict"),
    ("review_empty_findings", _r(lambda d: d.__setitem__("findings", [])), "empty-findings", "findings"),
    ("review_unresolved_scenario", _r(lambda d: d.__setitem__("target", "some-other")), "unresolved-scenario-ref", "'scn'"),
    ("review_stale", _r(lambda d: d.__setitem__("code_version", "f" * 40)), "stale-attestation", "review code_version"),
    ("review_revise", _r(lambda d: d.__setitem__("verdict", "REVISE")), "revise-verdict", "REVISE"),
    ("signoff_missing_review_ref", _s(lambda d: d.pop("review_ref")), "missing-field", "review_ref"),
    ("signoff_missing_kind", _s(lambda d: d.pop("attestation_kind")), "missing-field", "attestation_kind"),
    ("signoff_invalid_decision", _s(lambda d: d.__setitem__("decision", "MAYBE")), "invalid-enum", "decision"),
    ("signoff_missing_calibration", _s(lambda d: d.pop("calibration_status")), "missing-field", "calibration_status"),
    ("signoff_bad_date", _s(lambda d: d.__setitem__("date", "2026/06/22")), "invalid-format", "date"),
    ("signoff_unresolved_review_ref", _s(lambda d: d.__setitem__("review_ref", "review-999")), "unresolved-review-ref", "review-999"),
    ("signoff_stale", _s(lambda d: d.__setitem__("code_version", "f" * 40)), "stale-attestation", "signoff code_version"),
    ("signoff_rejected", _s(lambda d: d.__setitem__("decision", "REJECTED")), "rejected-decision", "REJECTED"),
    # WP-E2c.1 kind partition + the structural impossibility of a self-approval
    ("kind_mismatch", _s(lambda d: d.__setitem__("attestation_kind", "SYNTHETIC_SELF_CHECK")), "kind-mismatch", "SYNTHETIC_SELF_CHECK"),
    ("synthetic_signoff_approved", lambda r, s: (r.update(attestation_kind="SYNTHETIC_SELF_CHECK", verdict="SELF_CHECK_PASSED"), s.update(attestation_kind="SYNTHETIC_SELF_CHECK"))[0], "kind-decision-mismatch", "APPROVED"),
    ("synthetic_review_accept", lambda r, s: (r.update(attestation_kind="SYNTHETIC_SELF_CHECK"), s.update(attestation_kind="SYNTHETIC_SELF_CHECK", decision="EXTERNAL_REVIEW_PENDING"))[0], "kind-verdict-mismatch", "ACCEPT"),
    ("self_check_failed", lambda r, s: (r.update(attestation_kind="SYNTHETIC_SELF_CHECK", verdict="SELF_CHECK_PASSED"), s.update(attestation_kind="SYNTHETIC_SELF_CHECK", decision="SELF_CHECK_FAILED"))[0], "self-check-failed", "SELF_CHECK_FAILED"),
    # an INDEPENDENT signer not in the allow-list cannot mint its own independence (HOLE-1 fix: allow-list, not regex)
    ("unlisted_independent_signer", _s(lambda d: d.__setitem__("signed_by", "some unlisted signer")), "unlisted-independent-reviewer", "signed_by"),
    ("unlisted_independent_reviewer", _r(lambda d: d.__setitem__("reviewer", "some unlisted reviewer")), "unlisted-independent-reviewer", "reviewer"),
]


@pytest.mark.parametrize("name,mutate,code,token", _MUTATIONS, ids=[m[0] for m in _MUTATIONS])
def test_invalid_single_fault(name, mutate, code, token, tmp_path: Path) -> None:
    review, signoff = copy.deepcopy(REVIEW_BASE), copy.deepcopy(SIGNOFF_BASE)
    mutate(review, signoff)
    result = _run_pair(tmp_path, review, signoff)
    assert result.returncode == 1, f"{name}: {result.stdout}"
    findings = _findings(result.stderr)
    assert len(findings) == 1, f"{name}: expected one finding; got {findings}"
    assert code in findings[0] and token in findings[0], f"{name}: {findings[0]!r}"


# --- HOLE-1: independence is allow-listed, not self-declared --------------------------

def test_default_empty_allowlist_rejects_self_declared_independent(tmp_path: Path) -> None:
    # With the REAL repo allow-list (attestation_reviewers.yaml, empty), a self-declared INDEPENDENT pair
    # cannot pass -- nothing is independent until a human lists a reviewer. Proves the regex was not the
    # only guard: even an allow-list-free synthetic signer that dodges every flagged word is rejected.
    r, s = copy.deepcopy(REVIEW_BASE), copy.deepcopy(SIGNOFF_BASE)
    r.update(reviewer="Centaur Harness Agent v3")     # dodges any synthetic-word regex; still unlisted
    s.update(signed_by="automated pipeline")
    rp, sp = tmp_path / "review.yaml", tmp_path / "signoff.yaml"
    rp.write_text(yaml.safe_dump(r, sort_keys=False))
    sp.write_text(yaml.safe_dump(s, sort_keys=False))
    result = _run("--scenario-dir", str(SCN), "--review", str(rp), "--signoff", str(sp))  # default allow-list
    assert result.returncode == 1, result.stdout
    assert "unlisted-independent-reviewer" in result.stderr


# --- fail-closed (exit 2): never report clean on nothing ------------------------------

def test_fail_closed_on_empty_attestation(tmp_path: Path) -> None:
    (tmp_path / "review.yaml").write_text("\n")          # empty doc
    (tmp_path / "signoff.yaml").write_text(yaml.safe_dump(SIGNOFF_BASE))
    assert _run("--scenario-dir", str(SCN), "--review", str(tmp_path / "review.yaml"),
                "--signoff", str(tmp_path / "signoff.yaml")).returncode == 2


def test_fail_closed_on_missing_review(tmp_path: Path) -> None:
    (tmp_path / "signoff.yaml").write_text(yaml.safe_dump(SIGNOFF_BASE))
    assert _run("--scenario-dir", str(SCN), "--review", str(tmp_path / "nope.yaml"),
                "--signoff", str(tmp_path / "signoff.yaml")).returncode == 2


def test_fail_closed_on_broken_ledger(tmp_path: Path) -> None:
    scn = tmp_path / "scn"
    scn.mkdir()
    (scn / "scenario.yaml").write_text("schema_version: '1.0'\n")
    (scn / "run_ledger.yaml").write_text("not-a-mapping\n")  # no code_version -> can't bind
    (scn / "review.yaml").write_text(yaml.safe_dump(REVIEW_BASE))
    (scn / "signoff.yaml").write_text(yaml.safe_dump(SIGNOFF_BASE))
    assert _run("--scenario-dir", str(scn)).returncode == 2


def test_fail_closed_on_missing_scenario(tmp_path: Path) -> None:
    scn = tmp_path / "scn"
    scn.mkdir()
    (scn / "run_ledger.yaml").write_text("code_version: 'x'\n")  # no scenario.yaml
    (scn / "review.yaml").write_text(yaml.safe_dump(REVIEW_BASE))
    (scn / "signoff.yaml").write_text(yaml.safe_dump(SIGNOFF_BASE))
    assert _run("--scenario-dir", str(scn)).returncode == 2

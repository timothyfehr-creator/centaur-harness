"""Behavior tests for scripts/verify.py mode handling.

The mode-dispatch tests invoke the real CLI via subprocess so they exercise exit codes
exactly as CI and the acceptance commands do. The draft-composition tests import verify
in-process and stub ``_run_gate``, so the gate-failure path is exercised WITHOUT mutating
the shared repo or depending on git (the gates are subprocesses a monkeypatch can't
reach). Paths are computed from this file's location, so the tests pass regardless of cwd.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY = REPO_ROOT / "scripts" / "verify.py"

# Import the verify module in-process for the composition tests (additive to the
# subprocess style; verify.py has no import side effects -- main() is __main__-guarded).
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import verify  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


# --- mode dispatch (subprocess, real CLI) -----------------------------------------

def test_scaffold_mode_exits_zero() -> None:
    result = _run("--mode", "scaffold")
    assert result.returncode == 0, result.stderr
    # The success message proves the required-path check actually ran, rather
    # than scaffold trivially returning 0 without checking anything.
    assert "scaffold verification OK" in result.stdout


def test_default_invocation_exits_zero_and_is_scaffold() -> None:
    result = _run()
    assert result.returncode == 0, result.stderr
    # The default invocation must behave like scaffold mode.
    assert "scaffold" in result.stdout.lower()


def test_unknown_mode_fails_clearly() -> None:
    result = _run("--mode", "definitely-not-a-real-mode")
    assert result.returncode != 0
    assert "unknown mode" in result.stderr.lower()


def test_draft_mode_exits_zero_on_clean_repo() -> None:
    # WP4: draft composes scaffold + the evidence/safety gates and reports honestly.
    result = _run("--mode", "draft")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    # active checks ran and passed (agent grounding became active in WP5: now a [PASS],
    # no longer a [SKIP])
    assert "[PASS] scaffold" in out
    assert "source registry" in out
    assert "safety" in out
    assert "[PASS] agent grounding" in out
    # still-not-yet-implemented checks are reported, not silently omitted. Post-WP8/WP-E1 the
    # list shrank further: refuter review + human signoff + turn replay now run in `release`, so
    # what remains is only calibration SCORING (a backtest needing outcomes).
    assert "not yet implemented" in out.lower()
    assert "refuter review" not in out.lower()  # no longer "not implemented" -- it runs in release
    assert "turn replay" not in out.lower()     # WP-E1: now a release gate, not a draft [SKIP]
    # structural-only, and it must NOT claim analytical validity
    assert "STRUCTURAL ONLY" in out
    assert "not an analytical-validity claim" in out


def test_release_mode_exits_zero_on_attested_repo() -> None:
    # WP8: release is now available. On the clean, fully-attested example it passes and
    # carries the declared calibration -- but it must NOT claim analytical validity (§3).
    result = _run("--mode", "release")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "release OK" in out
    assert "[PASS] review + signoff attestation" in out
    assert "[PASS] run-ledger / reproducibility" in out
    assert "calibration: ILLUSTRATIVE" in out          # the declared status is surfaced
    assert "STRUCTURAL + ATTESTATION ONLY" in out
    assert "not an analytical-validity claim" in out
    # turn replay now RUNS in release (WP-E1) -- a [PASS], no longer a [SKIP]
    assert "[PASS] turn replay" in out


# --- draft composition logic (in-process, non-mutating) ---------------------------

def test_verify_draft_passes_when_all_gates_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        verify, "_run_gate",
        lambda root, script: {"name": script, "ok": True, "rc": 0, "detail": "OK"},
    )
    exit_code, results = verify.verify_draft(REPO_ROOT)
    assert exit_code == 0
    assert all(r["ok"] for r in results)
    # scaffold (in-process, real clean repo) + the subprocessed gates in DRAFT_GATES
    assert len(results) == 1 + len(verify.DRAFT_GATES)


def test_verify_draft_fails_when_a_gate_fails(monkeypatch) -> None:
    def fake_gate(root: Path, script: str) -> dict:
        ok = script != "validate_events.py"
        return {"name": script, "ok": ok, "rc": 0 if ok else 1,
                "detail": "OK" if ok else "boom"}

    monkeypatch.setattr(verify, "_run_gate", fake_gate)
    exit_code, results = verify.verify_draft(REPO_ROOT)
    assert exit_code == 1  # one failing active check -> draft fails, never false-passes
    failed = [r for r in results if not r["ok"]]
    assert len(failed) == 1 and "validate_events.py" in failed[0]["name"]


# --- release composition logic (in-process; proves §3 "never falsely passes") -----

def test_verify_release_passes_when_all_gates_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        verify, "_run_gate",
        lambda root, script: {"name": script, "ok": True, "rc": 0, "detail": "OK"},
    )
    exit_code, results, calibration = verify.verify_release(REPO_ROOT)
    assert exit_code == 0
    assert all(r["ok"] for r in results)
    # scaffold (in-process) + the draft gates + the release gates (run-ledger, attestation)
    assert len(results) == 1 + len(verify.DRAFT_GATES) + len(verify.RELEASE_GATES)
    assert calibration == "ILLUSTRATIVE"  # read from the real example signoff (not stubbed)


def test_verify_release_propagates_findings_as_one(monkeypatch) -> None:
    # A composed gate that reports findings (rc 1) must fail release with exit 1.
    def fake_gate(root: Path, script: str) -> dict:
        ok = script != "validate_review_signoff.py"
        return {"name": script, "ok": ok, "rc": 0 if ok else 1, "detail": "OK" if ok else "blocked"}

    monkeypatch.setattr(verify, "_run_gate", fake_gate)
    exit_code, _results, _cal = verify.verify_release(REPO_ROOT)
    assert exit_code == 1  # a REVISE/REJECTED/stale attestation blocks release, never passes


def test_verify_release_preserves_cannot_run_as_two(monkeypatch) -> None:
    # A gate that CANNOT RUN (rc 2) must propagate as exit 2, NOT collapse to 1 -- the
    # fail-closed distinction (harness error vs content finding) must survive composition.
    def fake_gate(root: Path, script: str) -> dict:
        rc = 2 if script == "validate_run_ledger.py" else 0
        return {"name": script, "ok": rc == 0, "rc": rc, "detail": "fail-closed" if rc else "OK"}

    monkeypatch.setattr(verify, "_run_gate", fake_gate)
    exit_code, _results, _cal = verify.verify_release(REPO_ROOT)
    assert exit_code == 2


def test_verify_release_worst_rc_when_mixed(monkeypatch) -> None:
    # findings (1) on one gate + cannot-run (2) on another -> the worst (2) wins.
    def fake_gate(root: Path, script: str) -> dict:
        rc = {"validate_review_signoff.py": 1, "validate_run_ledger.py": 2}.get(script, 0)
        return {"name": script, "ok": rc == 0, "rc": rc, "detail": str(rc)}

    monkeypatch.setattr(verify, "_run_gate", fake_gate)
    exit_code, _results, _cal = verify.verify_release(REPO_ROOT)
    assert exit_code == 2


def test_run_gate_fail_closed_when_subprocess_cannot_launch(monkeypatch) -> None:
    # A gate that cannot even run must be a FAILED check (rc 2), never silently dropped.
    def boom(*args, **kwargs):
        raise OSError("no interpreter")

    monkeypatch.setattr(verify.subprocess, "run", boom)
    result = verify._run_gate(REPO_ROOT, "validate_sources.py")
    assert result["ok"] is False
    assert result["rc"] == 2
    assert "fail-closed" in result["detail"]


def test_verify_py_not_in_draft_gates() -> None:
    # Guard against a future edit that would make draft subprocess itself (recursion).
    assert all(script != "verify.py" for _label, script in verify.DRAFT_GATES)

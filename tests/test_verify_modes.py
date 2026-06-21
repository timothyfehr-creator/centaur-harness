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
    # active checks ran and passed
    assert "[PASS] scaffold" in out
    assert "source registry" in out
    assert "safety" in out
    # not-yet-implemented checks are reported, not silently omitted
    assert "not yet implemented" in out.lower()
    assert "agent grounding" in out.lower()
    # structural-only, and it must NOT claim analytical validity
    assert "STRUCTURAL ONLY" in out
    assert "not an analytical-validity claim" in out


def test_release_mode_never_falsely_passes() -> None:
    # Release stays unavailable until its gates exist -- fail clearly, never pass.
    result = _run("--mode", "release")
    assert result.returncode == 2
    assert "release" in result.stderr.lower()
    # The distinct "unavailable / not yet implemented" wording must stay distinct from
    # the typo "unknown mode" branch, so a future reword can't blur the two.
    assert "not yet implemented" in result.stderr.lower()
    assert "unavailable" in result.stderr.lower()


# --- draft composition logic (in-process, non-mutating) ---------------------------

def test_verify_draft_passes_when_all_gates_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        verify, "_run_gate",
        lambda root, script: {"name": script, "ok": True, "rc": 0, "detail": "OK"},
    )
    exit_code, results = verify.verify_draft(REPO_ROOT)
    assert exit_code == 0
    assert all(r["ok"] for r in results)
    # scaffold (in-process, real clean repo) + the 5 subprocessed gates = 6 checks
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

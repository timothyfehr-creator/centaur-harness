"""Behavior tests for the PreToolUse security guardrail (.claude/hooks/security-deny.py).

The hook makes two honesty guarantees structural: an AI tool call cannot edit the attestation
surface (or the guardrail's own files), and cannot ``git push`` / ``gh pr merge`` to the shared
repo. These tests pin the deny/allow boundary so a future change cannot silently weaken it.

A DENY is signalled by printing a ``hookSpecificOutput.permissionDecision == "deny"`` object and
exiting 0; an ALLOW is exit 0 with no stdout.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "security-deny.py"


def _run(payload: dict) -> tuple[int, str]:
    proc = subprocess.run(
        [str(HOOK)], input=json.dumps(payload), capture_output=True, text=True
    )
    return proc.returncode, proc.stdout


def _is_deny(stdout: str) -> bool:
    if not stdout.strip():
        return False
    obj = json.loads(stdout)
    return obj.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


DENY_CASES = [
    ("Edit", {"file_path": "/repo/examples/x/attestation_reviewers.yaml"}),
    ("Edit", {"file_path": "/repo/examples/x/review.yaml"}),
    ("Write", {"file_path": "/repo/examples/x/signoff.yaml"}),
    ("Write", {"file_path": "/repo/.claude/hooks/security-deny.py"}),
    ("Edit", {"file_path": "/repo/.claude/settings.json"}),
    ("MultiEdit", {"edits": [{"file_path": "/a/ok.py"}, {"file_path": "/b/review.yaml"}]}),
]

ALLOW_CASES = [
    ("Edit", {"file_path": "/repo/core/resolver.py"}),
    ("Write", {"file_path": "/repo/examples/x/run_ledger.yaml"}),
    ("MultiEdit", {"edits": [{"file_path": "/a/ok.py"}, {"file_path": "/b/also_ok.py"}]}),
    # Hobby project: NO publish/merge ceremony — git push / merge are intentionally allowed.
    ("Bash", {"command": "git push origin main"}),
    ("Bash", {"command": "gh pr merge 5 --squash"}),
    ("Bash", {"command": "git status"}),
    ("Bash", {"command": "pytest -q"}),
]


@pytest.mark.parametrize("tool_name,tool_input", DENY_CASES)
def test_denies_protected_writes_and_publish(tool_name: str, tool_input: dict) -> None:
    code, out = _run({"tool_name": tool_name, "tool_input": tool_input})
    assert code == 0
    assert _is_deny(out), f"expected DENY for {tool_name} {tool_input}, got {out!r}"


@pytest.mark.parametrize("tool_name,tool_input", ALLOW_CASES)
def test_allows_ordinary_calls(tool_name: str, tool_input: dict) -> None:
    code, out = _run({"tool_name": tool_name, "tool_input": tool_input})
    assert code == 0
    assert not _is_deny(out), f"expected ALLOW for {tool_name} {tool_input}, got {out!r}"


def test_malformed_input_fails_open() -> None:
    proc = subprocess.run([str(HOOK)], input="not json", capture_output=True, text=True)
    assert proc.returncode == 0
    assert not proc.stdout.strip()

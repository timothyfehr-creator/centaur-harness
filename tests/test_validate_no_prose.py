"""Tests for scripts/validate_no_prose.py (WP-A1b — the global no-prose gate)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "validate_no_prose.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_no_prose as vnp  # noqa: E402


def test_committed_repo_is_prose_free() -> None:
    # the redacted scenarios + the exempt test fixtures must leave the whole repo prose-free
    r = subprocess.run([sys.executable, str(GATE)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _git_repo(tmp: Path, files: dict) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    for rel, data in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def _prose_response() -> bytes:
    return json.dumps({"role": "assistant", "content": [
        {"type": "text", "text": "Here is my detailed strategic reasoning about the enemy."},
        {"type": "tool_use", "name": "submit_command", "input": {"action_type": "X", "params": {}}}]}).encode()


def test_scan_catches_prose_in_a_tracked_file(tmp_path: Path) -> None:
    # a raw dump committed OUTSIDE run/llm/ (the adjacent-manhole the review flagged) is still caught
    repo = _git_repo(tmp_path, {"run/raw/debug.json": _prose_response(), "ok.py": "x = 1\n"})
    findings = vnp.scan(repo)
    assert len(findings) == 1 and findings[0][0] == "run/raw/debug.json"


def test_exempt_fixtures_are_not_flagged(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path, {"tests/fixtures/agent_bytes/valid/x.json": _prose_response()})
    assert vnp.scan(repo) == []


def test_non_response_json_is_not_flagged(tmp_path: Path) -> None:
    # a config/data JSON that happens to be valid JSON but is not a response body must not false-positive
    repo = _git_repo(tmp_path, {"data.json": json.dumps({"content": "just a string field"}).encode()})
    assert vnp.scan(repo) == []

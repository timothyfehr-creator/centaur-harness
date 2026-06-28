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


def test_scan_catches_unicode_escaped_key_prose(tmp_path: Path) -> None:
    # regression (slice-2 review BLOCKER 2): \u-escaped keys (content / type) parse as a response
    # with prose but defeat a literal-byte pre-filter. The escape-proof brace check must still scan it.
    crafted = ('{"\\u0063ontent":[{"\\u0074ype":"text","text":"BLUE will feint r1 then win on r2."}],'
               '"role":"assistant"}').encode()
    assert b'"content"' not in crafted and b'"type"' not in crafted   # the literal key bytes are absent...
    repo = _git_repo(tmp_path, {"run/raw/sneaky.json": crafted})
    findings = vnp.scan(repo)
    assert len(findings) == 1 and findings[0][0] == "run/raw/sneaky.json"   # ...but the scan still catches it


def test_scan_catches_bom_prefixed_and_array_wrapped_prose(tmp_path: Path) -> None:
    # landing-review BLOCKER (b)+(c): a BOM-prefixed response and a JSON-array-wrapped response both carry
    # committed prose; the gate must catch both (the brace pre-filter tolerates a BOM + a leading '[').
    body = json.dumps({"role": "assistant", "content": [{"type": "text", "text": "feint r1 then win on r2"}]})
    repo = _git_repo(tmp_path, {
        "run/raw/bom.json": b"\xef\xbb\xbf" + body.encode(),
        "run/raw/arr.json": ("[" + body + "]").encode(),
        "ok.py": "x = 1\n"})
    flagged = {f[0] for f in vnp.scan(repo)}
    assert flagged == {"run/raw/bom.json", "run/raw/arr.json"}


def test_scan_catches_tool_use_sibling_prose(tmp_path: Path) -> None:
    # landing-review BLOCKER (a): a committed tool_use block with a prose sibling must be caught.
    crafted = json.dumps({"role": "assistant", "content": [{"type": "tool_use", "name": "submit_command",
        "input": {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 30, "route": "r1"}},
        "scratch": "RED is overcommitted; feint r1 then route r2"}]}).encode()
    repo = _git_repo(tmp_path, {"run/raw/sib.json": crafted})
    assert len(vnp.scan(repo)) == 1


def test_non_response_json_is_not_flagged(tmp_path: Path) -> None:
    # a config/data JSON that happens to be valid JSON but is not a response body must not false-positive
    repo = _git_repo(tmp_path, {"data.json": json.dumps({"content": "just a string field"}).encode()})
    assert vnp.scan(repo) == []

"""Behavior tests for scripts/validate_agents.py (the WP5 agent-grounding gate).
Requires PyYAML.

Agent fixtures resolve against the *fixture* claims / assumptions / knowledge (via the CLI
flags), isolating the tests from the shipped factbase + example. Each invalid fixture is an
otherwise-fully-grounded agent with exactly ONE injected defect, so the single-finding
assertion holds (the grounding bar can otherwise co-fire with an unresolved-ref finding).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_agents.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "registries"
CLAIMS = FIXTURES / "valid" / "claims_minimal.yaml"
ASSUMPTIONS = REPO_ROOT / "tests" / "fixtures" / "assumptions" / "assumptions_minimal.yaml"
KNOWLEDGE = REPO_ROOT / "tests" / "fixtures" / "knowledge"


def _run(*args: str, claims: Path = CLAIMS, assumptions: Path = ASSUMPTIONS,
         knowledge: Path = KNOWLEDGE) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args,
         "--claims", str(claims), "--assumptions", str(assumptions),
         "--knowledge-dir", str(knowledge)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


def _findings(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.lstrip().startswith("- ")]


def test_valid_agents_fixture_passes() -> None:
    result = _run(str(FIXTURES / "valid" / "agents_minimal.yaml"))
    assert result.returncode == 0, result.stderr


def test_example_agents_resolves() -> None:
    # bare run -> the shipped example agents.yaml vs the real factbase + knowledge/.
    result = subprocess.run([sys.executable, str(VALIDATOR)],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "agent validation OK" in result.stdout


# (fixture name -> expected code, a token in the message). Two ungrounded fixtures isolate
# the two legs of the AND-bar (knowledge leg vs capability leg).
_INVALID = {
    "agents_no_knowledge": ("ungrounded-agent", "knowledge"),
    "agents_ungrounded": ("ungrounded-agent", "capability"),
    "agents_unresolved_knowledge": ("unresolved-knowledge-ref", "book-999"),
    "agents_unresolved_capability": ("unresolved-capability-ref", "claim-999"),
    "agents_unresolved_assumption": ("unresolved-assumption-ref", "assum-999"),
    "agents_duplicate_id": ("duplicate-id", "agent-001"),
    "agents_bad_type": ("invalid-enum", "type"),
    "agents_missing_schema_version": ("missing-schema-version", "schema_version"),
}


@pytest.mark.parametrize("name,code,token", [(n, c, t) for n, (c, t) in sorted(_INVALID.items())])
def test_invalid_agents_fixture_single_fault(name: str, code: str, token: str) -> None:
    result = _run(str(FIXTURES / "invalid" / f"{name}.yaml"))
    assert result.returncode == 1, result.stdout
    findings = _findings(result.stderr)
    assert len(findings) == 1, f"{name}: expected exactly one finding; got {findings}"
    assert code in findings[0], f"{name}: {findings[0]!r}"
    assert token in findings[0], f"{name}: {findings[0]!r}"


def test_assumptions_bad_entry_is_finding() -> None:
    # A usable assumptions registry with a malformed entry -> exit 1 finding (folded
    # assumptions validation), tagged assumptions[i]; the agent stays grounded.
    bad = REPO_ROOT / "tests" / "fixtures" / "assumptions" / "assumptions_bad_entry.yaml"
    result = _run(str(FIXTURES / "valid" / "agents_minimal.yaml"), assumptions=bad)
    assert result.returncode == 1, result.stdout
    findings = _findings(result.stderr)
    assert len(findings) == 1, findings
    assert "missing-field" in findings[0] and "assumptions[" in findings[0]


def test_fail_closed_on_missing_agents(tmp_path: Path) -> None:
    assert _run(str(tmp_path / "nope.yaml")).returncode == 2


def test_fail_closed_on_broken_claims(tmp_path: Path) -> None:
    result = _run(str(FIXTURES / "valid" / "agents_minimal.yaml"), claims=tmp_path / "nope.yaml")
    assert result.returncode == 2


def test_fail_closed_on_missing_assumptions(tmp_path: Path) -> None:
    result = _run(str(FIXTURES / "valid" / "agents_minimal.yaml"), assumptions=tmp_path / "nope.yaml")
    assert result.returncode == 2


def test_fail_closed_on_empty_knowledge_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = _run(str(FIXTURES / "valid" / "agents_minimal.yaml"), knowledge=empty)
    assert result.returncode == 2


def test_fail_closed_on_empty_agents_list(tmp_path: Path) -> None:
    f = tmp_path / "empty.yaml"
    f.write_text('schema_version: "1.0"\nagents: []\n')
    assert _run(str(f)).returncode == 2

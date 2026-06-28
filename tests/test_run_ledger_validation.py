"""Behavior tests for scripts/validate_run_ledger.py (the WP7 reproducibility gate).

Structural single-fault fixtures (integrity is short-circuited, so they isolate one code).
Integrity tests build a self-contained tmp mini-repo (copy of the scenario + factbase +
knowledge) so the REAL repo is never mutated and never `--write`-n (concurrent-session rule).
The default check is git-independent (content hashes only); only `--write` needs git, exercised
in one git-init'd tmp repo.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_run_ledger.py"
EXAMPLE_LEDGER = REPO_ROOT / "examples" / "ukraine_crimea_logistics" / "run_ledger.yaml"
INVALID = REPO_ROOT / "tests" / "fixtures" / "run_ledger" / "invalid"

import validate_run_ledger as vrl  # noqa: E402

ALL_LEDGERS = sorted((REPO_ROOT / "examples").glob("*/run_ledger.yaml"))


@pytest.mark.parametrize("ledger", ALL_LEDGERS, ids=lambda p: p.parent.name)
def test_every_committed_example_ledger_verifies_clean(ledger: Path) -> None:
    # RTH-3: CI (and this test) validate EVERY committed example ledger, not just the default Ukraine
    # one, so a stale/orphan engine-scenario ledger cannot land undetected (read-only; no --write).
    assert vrl.main([str(ledger)]) == 0


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(VALIDATOR), *args],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def _findings(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.lstrip().startswith("- ")]


def _mini_repo(tmp_path: Path, git: bool = False) -> tuple[Path, Path]:
    """A self-contained copy of the scenario + factbase + knowledge under tmp_path."""
    repo = tmp_path / "repo"
    scn = repo / "examples" / "scn"
    shutil.copytree(REPO_ROOT / "examples" / "ukraine_crimea_logistics", scn)
    shutil.copytree(REPO_ROOT / "factbase", repo / "factbase")
    shutil.copytree(REPO_ROOT / "knowledge", repo / "knowledge")
    if git:
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "-m", "init"], check=True)
    return repo, scn


def _write_ledger_in_process(ledger_path: Path, scn: Path, repo: Path) -> None:
    """Build a correct ledger without git (proves the check is git-independent)."""
    inputs = vrl.declared_inputs(scn, repo)
    ledger = {
        "schema_version": "1.0", "as_of_date": "2026-06-22", "code_version": "test-sha",
        "tool_version": "1.0", "generated_by": "test",
        "inputs": [{"path": p.relative_to(repo).as_posix(), "sha256": vrl._sha256(p)}
                   for p in inputs],
        "rng_seeds": None, "llm_steps": None,
    }
    ledger_path.write_text(yaml.safe_dump(ledger, sort_keys=False, width=4096), encoding="utf-8")


# --- the committed example ledger (the live lockfile-is-current guard) -------------

def test_committed_ledger_verifies() -> None:
    result = _run()
    assert result.returncode == 0, result.stderr
    assert "run-ledger OK" in result.stdout


def test_relative_ledger_path_verifies() -> None:
    # The documented `validate_run_ledger.py LEDGER` form may pass a RELATIVE path. That must
    # produce a verdict, not a ValueError traceback: declared_inputs() does p.relative_to(
    # repo_root), which needs scenario_dir resolved to absolute. Regression for the path bug.
    rel = EXAMPLE_LEDGER.relative_to(REPO_ROOT).as_posix()
    result = _run(rel)  # _run sets cwd=REPO_ROOT, so the relative path resolves there
    assert result.returncode == 0, result.stderr
    assert "run-ledger OK" in result.stdout


def test_committed_ledger_is_secret_scan_clean() -> None:
    # Locks the "no ledger field name triggers the generic secret rule" property against a
    # future field rename (e.g. to something containing 'token').
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"),
                             str(EXAMPLE_LEDGER)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- structural single-fault (static fixtures; integrity short-circuited) ----------

_STRUCTURAL = {
    "ledger_missing_code_version": ("missing-field", "code_version"),
    "ledger_bad_sha_format": ("invalid-format", "sha256"),
    "ledger_bad_date": ("invalid-format", "as_of_date"),
    "ledger_missing_path": ("missing-field", "path"),
    "ledger_non_null_placeholder": ("invalid-format", "rng_seeds"),
    "ledger_malformed_llm_steps": ("invalid-format", "response_sha256"),
}


def _valid_ledger_doc() -> dict:
    return {
        "schema_version": "1.0", "as_of_date": "2026-06-22", "code_version": "abc123",
        "tool_version": "1.0", "generated_by": "test",
        "inputs": [{"path": "factbase/claims.yaml", "sha256": "a" * 64}],
        "rng_seeds": None, "llm_steps": None,
    }


def test_populated_llm_steps_structure_accepts() -> None:
    # the WP-A1a migration: a null OR well-formed populated llm_steps passes the structural floor
    doc = _valid_ledger_doc()
    doc["llm_steps"] = [{"turn": 0, "calling_slot": "BLUE", "response_sha256": "b" * 64}]
    assert vrl.validate_structure(doc, "x") == []


def test_response_sha256_must_be_a_string_not_a_coercible_int() -> None:
    # fail-closed: a 64-digit int must NOT slip through (str() coercion would have matched the hex regex)
    doc = _valid_ledger_doc()
    doc["llm_steps"] = [{"turn": 0, "response_sha256": int("1" * 64)}]
    probs = vrl.validate_structure(doc, "x")
    assert len(probs) == 1 and probs[0][0] == "invalid-format" and "response_sha256" in probs[0][2]


def test_populated_rng_seeds_still_rejected() -> None:
    doc = _valid_ledger_doc()
    doc["rng_seeds"] = [1, 2, 3]
    probs = vrl.validate_structure(doc, "x")
    assert len(probs) == 1 and probs[0][0] == "invalid-format" and "rng_seeds" in probs[0][2]


def test_write_preserves_existing_llm_steps(tmp_path: Path) -> None:
    # a lockfile-drift --write regen must NOT wipe a populated llm_steps (carry-through)
    repo, scn = _mini_repo(tmp_path, git=True)
    ledger = scn / "run_ledger.yaml"
    assert _run(str(ledger), "--scenario-dir", str(scn), "--write").returncode == 0
    doc = yaml.safe_load(ledger.read_text())
    steps = [{"turn": 0, "calling_slot": "BLUE", "response_sha256": "c" * 64}]
    doc["llm_steps"] = steps
    ledger.write_text(yaml.safe_dump(doc, sort_keys=False, width=4096), encoding="utf-8")
    assert _run(str(ledger), "--scenario-dir", str(scn), "--write").returncode == 0
    assert yaml.safe_load(ledger.read_text())["llm_steps"] == steps  # preserved, not nulled
    assert _run(str(ledger), "--scenario-dir", str(scn)).returncode == 0  # and still verifies clean


@pytest.mark.parametrize("name,code,token", [(n, c, t) for n, (c, t) in sorted(_STRUCTURAL.items())])
def test_structural_single_fault(name: str, code: str, token: str) -> None:
    result = _run(str(INVALID / f"{name}.yaml"))
    assert result.returncode == 1, result.stdout
    findings = _findings(result.stderr)
    assert len(findings) == 1, f"{name}: {findings}"
    assert code in findings[0] and token in findings[0], f"{name}: {findings[0]!r}"


# --- integrity / drift (in-process ledger build; git-independent) ------------------

def test_check_is_clean_and_git_independent(tmp_path: Path) -> None:
    repo, scn = _mini_repo(tmp_path)  # NOT a git repo -> proves the check needs no git
    ledger = scn / "run_ledger.yaml"
    _write_ledger_in_process(ledger, scn, repo)
    result = _run(str(ledger), "--scenario-dir", str(scn))
    assert result.returncode == 0, result.stderr


def test_tampered_input_is_hash_mismatch(tmp_path: Path) -> None:
    repo, scn = _mini_repo(tmp_path)
    ledger = scn / "run_ledger.yaml"
    _write_ledger_in_process(ledger, scn, repo)
    claims = repo / "factbase" / "claims.yaml"
    claims.write_text(claims.read_text() + "\n# tampered\n")
    result = _run(str(ledger), "--scenario-dir", str(scn))
    assert result.returncode == 1
    assert "hash-mismatch" in result.stderr and "factbase/claims.yaml" in result.stderr
    assert "--write" in result.stderr  # the regenerate hint


def test_extra_input_fails(tmp_path: Path) -> None:
    repo, scn = _mini_repo(tmp_path)
    ledger = scn / "run_ledger.yaml"
    _write_ledger_in_process(ledger, scn, repo)
    (repo / "knowledge" / "country_books" / "new_book.yaml").write_text("id: book-new\n")
    result = _run(str(ledger), "--scenario-dir", str(scn))
    assert result.returncode == 1 and "extra-input" in result.stderr


def test_missing_input_fails(tmp_path: Path) -> None:
    repo, scn = _mini_repo(tmp_path)
    ledger = scn / "run_ledger.yaml"
    _write_ledger_in_process(ledger, scn, repo)
    (repo / "factbase" / "events.yaml").unlink()
    result = _run(str(ledger), "--scenario-dir", str(scn))
    assert result.returncode == 1 and "missing-input" in result.stderr


# --- --write (git-init'd tmp; never the real repo) ---------------------------------

def test_write_is_deterministic_and_picks_up_new_files(tmp_path: Path) -> None:
    repo, scn = _mini_repo(tmp_path, git=True)
    ledger = scn / "run_ledger.yaml"
    assert _run(str(ledger), "--scenario-dir", str(scn), "--write").returncode == 0
    first = ledger.read_text()
    assert yaml.safe_load(first)["inputs"], "round-trips to a non-empty inputs list"
    assert _run(str(ledger), "--scenario-dir", str(scn), "--write").returncode == 0
    assert ledger.read_text() == first  # byte-identical on re-write
    assert _run(str(ledger), "--scenario-dir", str(scn)).returncode == 0
    # add a declared input, regenerate, confirm it is now pinned and verifies
    (repo / "knowledge" / "country_books" / "extra.yaml").write_text("id: book-extra\n")
    assert _run(str(ledger), "--scenario-dir", str(scn), "--write").returncode == 0
    assert "knowledge/country_books/extra.yaml" in ledger.read_text()
    assert _run(str(ledger), "--scenario-dir", str(scn)).returncode == 0


# --- fail-closed (exit 2) ----------------------------------------------------------

def test_fail_closed_on_missing_ledger(tmp_path: Path) -> None:
    assert _run(str(tmp_path / "nope.yaml")).returncode == 2


def test_fail_closed_on_yaml_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("inputs: [a, b\n")  # unterminated flow seq
    assert _run(str(bad)).returncode == 2


def test_fail_closed_on_empty_inputs(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text('schema_version: "1.0"\ninputs: []\n')
    assert _run(str(empty)).returncode == 2

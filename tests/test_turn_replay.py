"""Tests for scripts/validate_turn_replay.py (WP-E1 turn-replay gate)."""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "core"))

import engine_recompute as er  # noqa: E402
import validate_turn_replay as vtr  # noqa: E402
VALIDATOR = REPO_ROOT / "scripts" / "validate_turn_replay.py"


def good() -> dict:
    return er.assemble_slice(0)["turn_record"]   # contested -> LOST, 1 draw


def codes(rec: dict) -> set:
    return {c for c, _, _ in vtr.check_record(rec, "x")}


def test_valid_record_replays_and_recomputes() -> None:
    assert vtr.check_record(good(), "x") == []


def test_tampered_resulting_state_is_caught() -> None:
    rec = copy.deepcopy(good())
    rec["resulting_state"]["state"]["entities"][0]["fields"]["loss_sink"]["value"] = 999
    assert "recompute-state-mismatch" in codes(rec)


def test_tampered_event_is_caught() -> None:
    # tamper the (reduce-neutral) BLOCK_ATTEMPTED route: grammar stays valid, so reduce succeeds,
    # but recomputation reproduces the ORIGINAL event batch -> recompute-event-mismatch
    rec = copy.deepcopy(good())
    assert rec["event_batch"][1]["event_type"] == "ROUTE_BLOCK_ATTEMPTED"
    rec["event_batch"][1]["route_id"] = "r2"
    assert "recompute-event-mismatch" in codes(rec)


def test_grammar_inconsistent_event_batch_is_caught() -> None:
    rec = copy.deepcopy(good())
    rec["event_batch"][0]["quantity"] = 5      # dispatch 5 but terminal 30 -> reduce rejects
    assert "reduce-failed" in codes(rec)


def test_decorative_seed_is_caught() -> None:
    rec = copy.deepcopy(er.assemble_slice(0, commands=[
        {"command_id": "cb", "turn": 0, "actor_id": "BLUE", "action_type": "DISPATCH_SUPPLY",
         "params": {"quantity": 20, "route": "r1"}}])["turn_record"])   # no draw -> rng None
    assert rec["rng"] is None
    rec["rng"] = {"master_seed": 0}             # inject a decorative seed
    assert "decorative-seed" in codes(rec)


def test_stale_transition_input_hash_is_caught() -> None:
    # EC-1: a committed record whose transition_input_hash no longer matches a fresh recompute (e.g. one
    # written before the `ruleset` preimage change) must be flagged -- even though it would otherwise
    # record-replay + recompute cleanly. This is the 'looks-valid-but-stale' class the gate must catch.
    rec = copy.deepcopy(good())
    rec["transition_input_hash"] = "0" * 64
    assert "transition-input-hash-mismatch" in codes(rec)


def test_unknown_resolver_id_fails_closed() -> None:
    # EC-2: a record carrying an unregistered resolver_id must NOT silently fall back to the logistics
    # resolver -- the gate refuses to replay it (fail-closed), per the harness's never-falsely-pass rule.
    rec = copy.deepcopy(good())
    rec["resolver_id"] = "no_such_resolver"
    assert "unknown-resolver-id" in codes(rec)


# --- CLI exit-code contract ---------------------------------------------------------

def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VALIDATOR), *args],
                          cwd=REPO_ROOT, capture_output=True, text=True)


def test_cli_passes_on_the_committed_record() -> None:
    assert _run().returncode == 0   # globs examples/**/run/turns/*.json -> the committed slice record


def test_cli_fail_closed_on_unreadable_path(tmp_path: Path) -> None:
    assert _run(str(tmp_path / "nope.json")).returncode == 2

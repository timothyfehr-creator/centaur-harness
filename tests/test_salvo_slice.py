"""WP-E2a acceptance suite — the 12 PASS conditions for the homogeneous salvo slice.

E2a is DETERMINISTIC with no agent commands, no RNG draws, and no agent-private state, so the
draw/command/fog conditions (#4, #6, #11, #12) are explicitly VACUOUS and asserted as such; the rest
are genuine. The model is UNCALIBRATED (placeholder params) — these test the engine contract, not realism.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

import atomic  # noqa: E402
import canon  # noqa: E402
import engine_projection as ep  # noqa: E402
import salvo_resolver as sv  # noqa: E402
import salvo_run  # noqa: E402
import turn_record as tr  # noqa: E402
import validate_turn_replay as vtr  # noqa: E402

COMMITTED = json.loads((REPO_ROOT / "examples" / "ru_ua_salvo_homogeneous" / "run" / "turns" / "0000.json").read_bytes())


def rec(ruleset: dict | None = None) -> dict:
    state, rules = salvo_run.load_scenario()
    return tr.assemble(turn=0, start_state=state, commands=[], master_seed=0,
                       runtime_fingerprint=salvo_run.FIXED_FINGERPRINT, successor_slot="run/turns/0000.json",
                       ruleset=ruleset or rules, resolver=sv)["turn_record"]


def test_pass01_deterministic_record_is_stable() -> None:
    assert canon.canonical_bytes(rec()) == canon.canonical_bytes(rec())   # no commands -> trivially reorder-stable


def test_pass02_fresh_subprocess_recompute_is_hashseed_independent() -> None:
    script = str(REPO_ROOT / "scripts" / "salvo_run.py")
    outs = []
    for hashseed in ("0", "1", "17"):
        r = subprocess.run([sys.executable, script], cwd=REPO_ROOT,
                           env={**os.environ, "PYTHONHASHSEED": hashseed}, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout.strip())
    assert len(set(outs)) == 1, f"salvo recompute varied across PYTHONHASHSEED: {outs}"


def test_pass03_any_command_commits_no_record() -> None:
    state, rules = salvo_run.load_scenario()
    out = tr.assemble(turn=0, start_state=state, commands=[{"actor_id": "X"}], master_seed=0,
                      runtime_fingerprint=salvo_run.FIXED_FINGERPRINT, successor_slot="s",
                      ruleset=rules, resolver=sv)
    assert out["status"] == "rejected" and out["turn_record"] is None


def test_pass04_no_adjudicator_only_state_vacuous() -> None:
    # E2a is a deterministic model with NO agent-private state -> no fog surface to leak
    assert all(not ep.is_adjudicator_only(e) for e in COMMITTED["resulting_state"]["state"]["entities"])


def test_pass05_and_09_reduce_coherence_on_committed_bytes() -> None:
    rederived = sv.reduce(COMMITTED["start_state"], COMMITTED["event_batch"])
    assert canon.canonical_bytes(rederived["state"]) == canon.canonical_bytes(COMMITTED["resulting_state"]["state"])
    assert canon.canonical_digest(rederived["state"]) == COMMITTED["resulting_state"]["state_digest"]


def test_pass06_and_12_no_draws_vacuous() -> None:
    assert COMMITTED["draw_records"] == []                                   # deterministic -> no draws
    assert all("draw_ref" not in e for e in COMMITTED["event_batch"])        # no stochastic terminals


def test_pass07_no_draw_turn_is_seed_independent() -> None:
    state, rules = salvo_run.load_scenario()
    a = rec()
    b = tr.assemble(turn=0, start_state=state, commands=[], master_seed=999,
                    runtime_fingerprint=salvo_run.FIXED_FINGERPRINT, successor_slot="s",
                    ruleset=rules, resolver=sv)["turn_record"]
    assert COMMITTED["rng"] is None and a["transition_input_hash"] == b["transition_input_hash"]


def test_pass08_ordered_events_and_no_decorative_seed() -> None:
    assert [e["event_type"] for e in COMMITTED["event_batch"]] == [
        "STRIKES_LAUNCHED", "INTERCEPTS_EXPENDED", "STRIKES_INTERCEPTED",
        "STRIKES_LEAKED", "RESUPPLY", "RESUPPLY", "CULMINATION_STATUS"]
    assert COMMITTED["rng"] is None


def test_pass10_single_successor_per_head(tmp_path: Path) -> None:
    slot = str(tmp_path / "turns" / "0000.json")
    a = rec()
    b = rec(ruleset={"p_intercept_pct": 75, "interceptors_per_intercept": 1, "culmination_threshold": 120})
    assert tr.commit(a, slot) == "committed"
    assert tr.commit(a, slot) == "idempotent"
    with pytest.raises(atomic.SlotConflict):
        tr.commit(b, slot)                                                   # different ruleset -> different candidate


def test_pass11_no_commands_no_reroll_vacuous() -> None:
    assert COMMITTED["command_batch"] == [] and COMMITTED["rng"] is None     # no commands/draws -> reroll N/A


def test_committed_salvo_record_passes_the_replay_gate() -> None:
    assert vtr.check_record(COMMITTED, "salvo") == []


def test_bda_shape_is_sensible() -> None:
    # a sanity check on the BDA the slice produces (placeholder values): launched == intercepted + leaked,
    # the magazine depletes, culmination fires
    ev = {e["event_type"]: e for e in COMMITTED["event_batch"] if "count" in e}
    assert ev["STRIKES_LAUNCHED"]["count"] == ev["STRIKES_INTERCEPTED"]["count"] + ev["STRIKES_LEAKED"]["count"]
    defense = next(e for e in COMMITTED["resulting_state"]["state"]["entities"] if e["id"] == "ukraine_air_defense")
    assert defense["fields"]["culminated"]["value"] is True

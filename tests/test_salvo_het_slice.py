"""WP-E2b1 acceptance suite — the 12 PASS conditions for the heterogeneous salvo slice.

E2b1 is DETERMINISTIC with no agent commands, no RNG draws, and no agent-private state, so #4/#6/#11/#12
are explicitly VACUOUS and asserted as such; the rest are genuine. UNCALIBRATED — these test the engine
contract, not realism. Includes a REGRESSION GUARD that the shipped E2a homogeneous golden vector is
byte-unchanged (its transition_input_hash still recomputes) after the new resolver + registry landed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import atomic  # noqa: E402
import canon  # noqa: E402
import engine_projection as ep  # noqa: E402
import salvo_resolver_het as sh  # noqa: E402
import salvo_het_run  # noqa: E402
import turn_record as tr  # noqa: E402
import validate_turn_replay as vtr  # noqa: E402

COMMITTED = json.loads((REPO_ROOT / "examples" / "ru_ua_salvo_heterogeneous" / "run" / "turns" / "0000.json").read_bytes())
E2A = json.loads((REPO_ROOT / "examples" / "ru_ua_salvo_homogeneous" / "run" / "turns" / "0000.json").read_bytes())


def rec(ruleset: dict | None = None) -> dict:
    state, rules = salvo_het_run.load_scenario()
    return tr.assemble(turn=0, start_state=state, commands=[], master_seed=0,
                       runtime_fingerprint=salvo_het_run.FIXED_FINGERPRINT, successor_slot="run/turns/0000.json",
                       ruleset=ruleset or rules, resolver=sh)["turn_record"]


def test_pass01_deterministic_record_is_stable() -> None:
    assert canon.canonical_bytes(rec()) == canon.canonical_bytes(rec())


def test_pass02_fresh_subprocess_recompute_is_hashseed_independent() -> None:
    script = str(REPO_ROOT / "scripts" / "salvo_het_run.py")
    outs = []
    for hashseed in ("0", "1", "17"):
        r = subprocess.run([sys.executable, script], cwd=REPO_ROOT,
                           env={**os.environ, "PYTHONHASHSEED": hashseed}, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout.strip())
    assert len(set(outs)) == 1, f"het recompute varied across PYTHONHASHSEED: {outs}"


def test_pass03_any_command_commits_no_record() -> None:
    state, rules = salvo_het_run.load_scenario()
    out = tr.assemble(turn=0, start_state=state, commands=[{"actor_id": "X"}], master_seed=0,
                      runtime_fingerprint=salvo_het_run.FIXED_FINGERPRINT, successor_slot="s",
                      ruleset=rules, resolver=sh)
    assert out["status"] == "rejected" and out["turn_record"] is None


def test_pass03b_out_of_range_ruleset_commits_no_record() -> None:
    # the crash-class fix at the assemble boundary: a bad ruleset is a rejection, not a record.
    state, rules = salvo_het_run.load_scenario()
    out = tr.assemble(turn=0, start_state=state, commands=[], master_seed=0,
                      runtime_fingerprint=salvo_het_run.FIXED_FINGERPRINT, successor_slot="s",
                      ruleset={**rules, "p_intercept_pct": {"drone": 150, "cruise": 65}}, resolver=sh)
    assert out["status"] == "rejected" and out["turn_record"] is None


def test_pass04_no_adjudicator_only_state_vacuous() -> None:
    # E2b1 has NO agent-private state -> no fog surface to leak
    assert all(not ep.is_adjudicator_only(e) for e in COMMITTED["resulting_state"]["state"]["entities"])


def test_pass05_and_09_reduce_coherence_on_committed_bytes() -> None:
    rederived = sh.reduce(COMMITTED["start_state"], COMMITTED["event_batch"])
    assert canon.canonical_bytes(rederived["state"]) == canon.canonical_bytes(COMMITTED["resulting_state"]["state"])
    assert canon.canonical_digest(rederived["state"]) == COMMITTED["resulting_state"]["state_digest"]


def test_pass06_and_12_no_draws_vacuous() -> None:
    assert COMMITTED["draw_records"] == []
    assert all("draw_ref" not in e for e in COMMITTED["event_batch"])


def test_pass07_no_draw_turn_is_seed_independent() -> None:
    state, rules = salvo_het_run.load_scenario()
    a = rec()
    b = tr.assemble(turn=0, start_state=state, commands=[], master_seed=999,
                    runtime_fingerprint=salvo_het_run.FIXED_FINGERPRINT, successor_slot="s",
                    ruleset=rules, resolver=sh)["turn_record"]
    assert COMMITTED["rng"] is None and a["transition_input_hash"] == b["transition_input_hash"]


def test_pass08_ordered_events_and_no_decorative_seed() -> None:
    expected = (["STRIKES_LAUNCHED"] * 3 + ["INTERCEPTS_EXPENDED"] * 3 + ["STRIKES_INTERCEPTED"] * 3 +
                ["STRIKES_LEAKED"] * 3 + ["RESUPPLY_STRIKE"] * 3 + ["RESUPPLY_INTERCEPTOR"] * 3 +
                ["BALLISTIC_LEAK_BAND", "LETHALITY_STATUS", "MAGAZINE_STATUS", "CULMINATION_STATUS",
                 "TURN_ADVANCED"])
    assert [e["event_type"] for e in COMMITTED["event_batch"]] == expected
    assert COMMITTED["rng"] is None


def test_pass10_single_successor_per_head(tmp_path: Path) -> None:
    slot = str(tmp_path / "turns" / "0000.json")
    _, rules = salvo_het_run.load_scenario()
    a = rec()
    b = rec(ruleset={**rules, "lethality_floor_pct": 90})    # different ruleset -> different candidate
    assert tr.commit(a, slot) == "committed"
    assert tr.commit(a, slot) == "idempotent"
    with pytest.raises(atomic.SlotConflict):
        tr.commit(b, slot)


def test_pass11_no_commands_no_reroll_vacuous() -> None:
    assert COMMITTED["command_batch"] == [] and COMMITTED["rng"] is None


def test_committed_het_record_passes_the_replay_gate() -> None:
    assert vtr.check_record(COMMITTED, "het") == []


def test_e2a_golden_vector_is_byte_unchanged_regression_guard() -> None:
    # the new resolver + registry + STOCHASTIC_TERMINALS refactor must NOT perturb the shipped E2a vector:
    # it still passes the gate, which includes a transition_input_hash recompute (so the hash is unchanged).
    assert vtr.check_record(E2A, "e2a-regression") == []


def test_bda_shape_is_sensible() -> None:
    ev = {(e["event_type"], e.get("threat")): e["count"] for e in COMMITTED["event_batch"] if "count" in e and "threat" in e}
    for t in ("drone", "cruise", "ballistic"):
        assert ev[("STRIKES_LAUNCHED", t)] == ev[("STRIKES_INTERCEPTED", t)] + ev[("STRIKES_LEAKED", t)]
    # saturation bit: drone's salvo is above the threshold, so its leak fraction exceeds cruise's
    assert ev[("STRIKES_LEAKED", "drone")] > 0 and ev[("STRIKES_INTERCEPTED", "drone")] > 0
    # the magazine leading indicator + culmination are reported and (turn 0) not yet culminated
    net = next(e for e in COMMITTED["resulting_state"]["state"]["entities"] if e["id"] == "ukraine_air_defense")
    assert net["fields"]["culminated"]["value"] is False

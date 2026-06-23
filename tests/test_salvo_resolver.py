"""Unit tests for core/salvo_resolver.py (WP-E2a homogeneous deterministic salvo).

ILLUSTRATIVE: all parameters are ASSUMED placeholders. These test the MATH and the engine-interface
behavior, not any real-world claim (the model is UNCALIBRATED until the WP-E2c backtest).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))

import canon  # noqa: E402
import salvo_resolver as sv  # noqa: E402

RULES = {"p_intercept_pct": 80, "interceptors_per_intercept": 1, "culmination_threshold": 120}


def make_state(strike_inv=10000, launch=1500, production=1500, interceptors=1200, resupply=60) -> dict:
    return {"schema_version": "1.0", "state": {"as_of_turn": 0, "entities": [
        {"id": "russia_strikeforce", "type": "STRIKE_FORCE", "fields": {
            "strike_inventory": {"value": strike_inv, "unit": "munitions"},
            "weekly_launch": {"value": launch, "unit": "munitions/week"},
            "weekly_production": {"value": production, "unit": "munitions/week"},
            "cumulative_launched": {"value": 0, "unit": "munitions"},
            "cumulative_leaked": {"value": 0, "unit": "munitions"}}},
        {"id": "ukraine_air_defense", "type": "AIR_DEFENSE", "fields": {
            "interceptor_inventory": {"value": interceptors, "unit": "interceptors"},
            "weekly_resupply": {"value": resupply, "unit": "interceptors/week"},
            "cumulative_intercepted": {"value": 0, "unit": "munitions"},
            "culminated": {"value": False, "unit": "bool"}}}]}}

def count(events, et): return next((e["count"] for e in events if e["event_type"] == et), None)
def fld(state, eid, f): return sv._v(state, eid, f)


# --- the math ----------------------------------------------------------------------

def test_saturated_week_golden() -> None:
    # 1500 launched, only 1200 interceptors -> 1200 attempted, 80% -> 960 intercepted, 540 leaked
    out = sv.transition(make_state(), [], ruleset=RULES)
    ev = out["events"]
    assert (count(ev, "STRIKES_LAUNCHED"), count(ev, "STRIKES_INTERCEPTED"), count(ev, "STRIKES_LEAKED")) == (1500, 960, 540)
    st = out["resulting_state"]
    assert fld(st, "ukraine_air_defense", "interceptor_inventory") == 60      # 1200 - 1200 + 60
    assert fld(st, "russia_strikeforce", "cumulative_leaked") == 540

def test_unsaturated_week_uses_full_intercept_rate() -> None:
    # plenty of interceptors -> attempted == launched; 80% of 1000 = 800 intercepted, 200 leaked
    out = sv.transition(make_state(launch=1000, interceptors=5000), [], ruleset=RULES)
    assert (count(out["events"], "STRIKES_INTERCEPTED"), count(out["events"], "STRIKES_LEAKED")) == (800, 200)

def test_launch_is_capped_by_strike_inventory() -> None:
    out = sv.transition(make_state(strike_inv=400, launch=1500), [], ruleset=RULES)
    assert count(out["events"], "STRIKES_LAUNCHED") == 400

def test_conservation_launched_equals_intercepted_plus_leaked() -> None:
    for launch, inter in [(1500, 1200), (1000, 5000), (200, 0), (0, 1000)]:
        ev = sv.transition(make_state(launch=launch, interceptors=inter), [], ruleset=RULES)["events"]
        assert count(ev, "STRIKES_LAUNCHED") == count(ev, "STRIKES_INTERCEPTED") + count(ev, "STRIKES_LEAKED")

def test_culmination_flag_tracks_threshold() -> None:
    culm = sv.transition(make_state(interceptors=1200, resupply=60), [], ruleset=RULES)   # -> 60 < 120
    assert fld(culm["resulting_state"], "ukraine_air_defense", "culminated") is True
    ok = sv.transition(make_state(launch=100, interceptors=5000, resupply=60), [], ruleset=RULES)  # plenty left
    assert fld(ok["resulting_state"], "ukraine_air_defense", "culminated") is False

def test_inventories_stay_non_negative() -> None:
    st = sv.transition(make_state(strike_inv=100, launch=1500, interceptors=50), [], ruleset=RULES)["resulting_state"]
    assert fld(st, "russia_strikeforce", "strike_inventory") >= 0
    assert fld(st, "ukraine_air_defense", "interceptor_inventory") >= 0


# --- engine-interface behavior -----------------------------------------------------

def test_deterministic_no_draws() -> None:
    a = sv.transition(make_state(), [], ruleset=RULES)
    b = sv.transition(make_state(), [], ruleset=RULES)
    assert a["draws"] == [] and a["events"] == b["events"]

def test_any_command_is_rejected_zero_mutation() -> None:
    state = make_state()
    out = sv.transition(state, [{"actor_id": "X"}], ruleset=RULES)
    assert out["status"] == "rejected" and out["resulting_state"] is state

def test_reduce_is_the_sole_constructor() -> None:
    out = sv.transition(make_state(), [], ruleset=RULES)
    rederived = sv.reduce(make_state(), out["events"])
    assert canon.canonical_bytes(rederived["state"]) == canon.canonical_bytes(out["resulting_state"]["state"])

def test_reduce_rejects_unknown_event() -> None:
    with pytest.raises(sv.SalvoError):
        sv.reduce(make_state(), [{"event_type": "NONSENSE"}])

def test_default_ruleset_applies_when_none() -> None:
    # transition with ruleset=None uses DEFAULT_RULESET (p=80) -> same as explicit RULES
    assert sv.transition(make_state(), [], ruleset=None)["events"] == sv.transition(make_state(), [], ruleset=RULES)["events"]

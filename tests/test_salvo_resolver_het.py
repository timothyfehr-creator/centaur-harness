"""Unit tests for core/salvo_resolver_het.py (WP-E2b1 heterogeneous salvo).

Covers the red-team-mandated math fixes: per-threat-subpool capped intercept, consumed-decoupled-from-
launched, no max(0,..) clamp, MONOTONE saturation (F3), round-ONCE-per-threat-subpool grain (F4),
ruleset-range rejection (the crash-class fix), hybrid culmination (sustained-k streak),
reduce-sole-constructor, and homogeneous-equivalence.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))

import canon  # noqa: E402
import salvo_resolver_het as sh  # noqa: E402


def _ent(eid: str, etype: str, **fields) -> dict:
    return {"id": eid, "type": etype, "fields": {k: {"value": v, "unit": "x"} for k, v in fields.items()}}


def make_state(*, drone=(1000, 5000, 1000), cruise=(500, 3000, 500), ballistic=(200, 2000, 200),
               short=(1500, 40), longi=(800, 20), pac3=(600, 30), streak=0, as_of_turn=0) -> dict:
    """drone/cruise/ballistic = (weekly_launch, strike_inventory, weekly_production);
    short/longi/pac3 = (interceptor_inventory, weekly_resupply)."""
    def strike(eid, t):
        return _ent(eid, "STRIKE_FORCE", weekly_launch=t[0], strike_inventory=t[1], weekly_production=t[2],
                    cumulative_launched=0, cumulative_leaked=0)

    def intc(eid, t):
        return _ent(eid, "AIR_DEFENSE", interceptor_inventory=t[0], weekly_resupply=t[1])

    network = _ent("ukraine_air_defense", "AIR_DEFENSE", cumulative_intercepted=0,
                   streak_drone=streak, streak_cruise=streak, streak_ballistic=streak,
                   lethality_collapsed=False, magazine_non_depleting=False, magazine_weeks_remaining=0,
                   magazine_stock_constrained=False, culminated=False)
    return {"schema_version": "1.0", "state": {"as_of_turn": as_of_turn, "entities": [
        strike("russia_strike_drone", drone), strike("russia_strike_cruise", cruise),
        strike("russia_strike_ballistic", ballistic),
        intc("ukraine_intc_short", short), intc("ukraine_intc_long", longi),
        intc("ukraine_intc_pac3", pac3), network]}}


def evmap(events: list) -> dict:
    """threat/type -> count for a given event_type, e.g. ev('STRIKES_LAUNCHED')['drone']."""
    out: dict = {}
    for e in events:
        key = e.get("threat") or e.get("interceptor_type")
        if key is not None and "count" in e:
            out.setdefault(e["event_type"], {})[key] = e["count"]
    return out


def status(events: list, etype: str) -> dict:
    return next(e for e in events if e["event_type"] == etype)


# --- conservation, caps, non-negativity (default 3x3 config) -------------------------------------------

def test_default_transition_resolves_with_conservation_and_caps() -> None:
    out = sh.transition(make_state(), [], turn=0)
    assert out["status"] == "resolved"
    ev = evmap(out["events"])
    for t in ("drone", "cruise", "ballistic"):
        assert ev["STRIKES_LAUNCHED"][t] == ev["STRIKES_INTERCEPTED"][t] + ev["STRIKES_LEAKED"][t]
        assert ev["STRIKES_INTERCEPTED"][t] <= ev["STRIKES_LAUNCHED"][t]                  # no overkill
    for t in ("drone", "cruise", "ballistic"):
        assert sh._v(out["resulting_state"], "russia_strike_" + t, "strike_inventory") >= 0
    for i in ("short", "long", "pac3"):
        assert sh._v(out["resulting_state"], "ukraine_intc_" + i, "interceptor_inventory") >= 0


# --- homogeneous-equivalence: a degenerate single-threat ruleset reproduces E2a's 1500/960/540 ---------

def test_homogeneous_equivalence_reproduces_e2a_arithmetic() -> None:
    state = {"schema_version": "1.0", "state": {"as_of_turn": 0, "entities": [
        _ent("russia_strike_drone", "STRIKE_FORCE", weekly_launch=1500, strike_inventory=10000,
             weekly_production=1500, cumulative_launched=0, cumulative_leaked=0),
        _ent("ukraine_intc_short", "AIR_DEFENSE", interceptor_inventory=1200, weekly_resupply=60),
        _ent("ukraine_air_defense", "AIR_DEFENSE", cumulative_intercepted=0, streak_drone=0,
             streak_cruise=0, streak_ballistic=0, lethality_collapsed=False, magazine_non_depleting=False,
             magazine_weeks_remaining=0, magazine_stock_constrained=False, culminated=False)]}}
    ruleset = {"threats": ["drone"], "interceptors": ["short"], "p_intercept_pct": {"drone": 80},
               "per_pairing": {"drone": {"short": 1}}, "allocation_priority": {"drone": ["short"]},
               "threat_order": ["drone"], "weekly_engagement_capacity": {"drone": 100000},
               "saturation_threshold": {"drone": 100000}, "saturation_retained_pct": {"drone": 70}}
    out = sh.transition(state, [], turn=0, ruleset=ruleset)
    ev = evmap(out["events"])
    assert ev["STRIKES_LAUNCHED"]["drone"] == 1500            # min(1500, 10000)
    assert ev["STRIKES_INTERCEPTED"]["drone"] == 960          # min(1500, 1200*80//100)
    assert ev["STRIKES_LEAKED"]["drone"] == 540               # 1500 - 960
    assert ev["INTERCEPTS_EXPENDED"]["short"] == 1200         # consumed = attempts * per(=1)


# --- consumed is tracked SEPARATELY and NOT capped by launched (per > 1 burns the magazine) ------------

def test_consumed_not_capped_by_launched() -> None:
    # ballistic per=2: firing N interceptors at N/2 incoming still burns N from the magazine, even though
    # intercepted is capped at launched. consumed (magazine burn) must reflect the full firing.
    state = make_state(ballistic=(200, 2000, 0), pac3=(1000, 0), drone=(0, 0, 0), cruise=(0, 0, 0),
                       short=(0, 0), longi=(0, 0))
    out = sh.transition(state, [], turn=0)
    ev = evmap(out["events"])
    consumed_pac3 = ev["INTERCEPTS_EXPENDED"]["pac3"]
    intercepted_ball = ev["STRIKES_INTERCEPTED"]["ballistic"]
    assert consumed_pac3 == 400                               # 200 attempts * per(=2)
    assert intercepted_ball <= 200                            # capped at launched
    assert consumed_pac3 > intercepted_ball                   # magazine burn NOT hidden by the cap
    assert consumed_pac3 > ev["STRIKES_LAUNCHED"]["ballistic"]  # not capped by launched either


# --- saturation: above the threshold, attempts (hence intercepts) degrade; high default is inert -------

def test_saturation_degrades_intercepts_above_threshold() -> None:
    # drone launch 2000 with abundant interceptors. Saturated (threshold 1000, retained 50%) leaks MORE
    # than the same week unsaturated (threshold above the salvo).
    base = make_state(drone=(2000, 10000, 0), cruise=(0, 0, 0), ballistic=(0, 0, 0),
                      short=(100000, 0), longi=(0, 0), pac3=(0, 0))
    sat = {"saturation_threshold": {"drone": 1000, "cruise": 1000, "ballistic": 1000},
           "saturation_retained_pct": {"drone": 50, "cruise": 70, "ballistic": 70}}
    unsat = {"saturation_threshold": {"drone": 100000, "cruise": 100000, "ballistic": 100000}}
    leaked_sat = evmap(sh.resolve(base, sat)[0])["STRIKES_LEAKED"]["drone"]
    leaked_unsat = evmap(sh.resolve(base, unsat)[0])["STRIKES_LEAKED"]["drone"]
    assert leaked_sat > leaked_unsat


def test_saturation_is_monotone_across_the_threshold() -> None:
    # F3 regression (external red-team): above the threshold, attempts (hence intercepts, with abundant
    # supply) must be MONOTONE NON-DECREASING in launches. The old discontinuous ``base_cap * retained``
    # form fell off a cliff at threshold+1 (launch 1000 -> 800 intercepts, launch 1001 -> 400).
    sat = {"saturation_threshold": {"drone": 1000, "cruise": 1000, "ballistic": 1000},
           "saturation_retained_pct": {"drone": 50, "cruise": 70, "ballistic": 70}}
    prev = -1
    for launch in (500, 999, 1000, 1001, 1200, 1500, 2000, 5000, 50000):
        state = make_state(drone=(launch, 1_000_000, 0), cruise=(0, 0, 0), ballistic=(0, 0, 0),
                           short=(10_000_000, 0), longi=(0, 0), pac3=(0, 0))
        got = evmap(sh.resolve(state, _full_ruleset(**sat))[0])["STRIKES_INTERCEPTED"]["drone"]
        assert got >= prev, f"intercepts dropped at launch={launch}: {got} < {prev} (non-monotone saturation)"
        prev = got


def test_multi_cell_grain_invariance_rounds_once_per_threat() -> None:
    # F4 regression (external red-team): a threat split across two interceptor types at 80% with 2 launched
    # must intercept 1 (round-once: floor(2*0.8)=1), NOT 0 (per-cell: floor(0.8)+floor(0.8)=0). The split is
    # forced by a short magazine of exactly 1, spilling the 2nd attempt to ``long`` (both at per=1).
    state = make_state(drone=(2, 100, 0), cruise=(0, 0, 0), ballistic=(0, 0, 0),
                       short=(1, 0), longi=(100, 0), pac3=(0, 0))
    ev = evmap(sh.resolve(state)[0])
    assert ev["STRIKES_INTERCEPTED"]["drone"] == 1     # round-once-per-threat; per-cell flooring gives 0


def test_ballistic_band_brackets_central_and_propagates() -> None:
    # F5 regression (external red-team): the reported ballistic leak band must BRACKET the deterministic
    # central count even for SMALL salvos (the old form floored both edges -> leak_high could fall BELOW
    # the central count, an inverted/decorative band). The band holds the magazine-constrained attempts
    # fixed and varies the exogenous leak rate, so it is non-decorative and its effective-rate edges order.
    for lb in (1, 2, 3, 5, 7, 11, 37, 80, 150):
        state = make_state(ballistic=(lb, 100000, 0), drone=(0, 0, 0), cruise=(0, 0, 0),
                           short=(0, 0), longi=(0, 0), pac3=(1_000_000, 0))
        ev = sh.resolve(state)[0]
        band = status(ev, "BALLISTIC_LEAK_BAND")
        central = evmap(ev)["STRIKES_LEAKED"]["ballistic"]
        assert band["leak_low"] <= central <= band["leak_high"], (lb, band, central)
        assert band["eff_pct_low"] <= band["eff_pct_high"]          # worst-case intercept <= best-case


# --- ruleset-range rejection (the crash-class fix) ----------------------------------------------------

def _full_ruleset(**over) -> dict:
    r = copy.deepcopy(sh.DEFAULT_RULESET)
    r.update(over)
    return r


def test_ruleset_pct_over_100_is_rejected() -> None:
    out = sh.transition(make_state(), [], ruleset=_full_ruleset(p_intercept_pct={"drone": 150, "cruise": 65}))
    assert out["status"] == "rejected"
    assert any(code == "p-out-of-range" for code, _ in out["rejections"])


def test_ruleset_per_zero_is_rejected_not_zerodivision() -> None:
    out = sh.transition(make_state(), [],
                        ruleset=_full_ruleset(per_pairing={"drone": {"short": 0, "long": 1},
                                                           "cruise": {"long": 1, "short": 2},
                                                           "ballistic": {"pac3": 2}}))
    assert out["status"] == "rejected"
    assert any(code == "per-out-of-range" for code, _ in out["rejections"])


def test_ruleset_bad_ballistic_range_is_rejected() -> None:
    out = sh.transition(make_state(), [], ruleset=_full_ruleset(ballistic_leak_floor_pct=40,
                                                                ballistic_leak_high_pct=20))
    assert out["status"] == "rejected"
    assert any(code == "ballistic-leak-range-invalid" for code, _ in out["rejections"])


def test_ruleset_float_pct_is_rejected_before_canon() -> None:
    out = sh.transition(make_state(), [], ruleset=_full_ruleset(p_intercept_pct={"drone": 0.8, "cruise": 65}))
    assert out["status"] == "rejected"
    assert any(code == "wrong-type" for code, _ in out["rejections"])


def test_a_rejected_ruleset_yields_no_record_and_no_mutation() -> None:
    state = make_state()
    out = sh.transition(state, [], ruleset=_full_ruleset(culmination_k_weeks=0))
    assert out["status"] == "rejected" and out["resulting_state"] is state


def test_partial_capacity_override_is_rejected_not_keyerror() -> None:
    # a SHALLOW nested override dropping a threat from a saturation/capacity map must be REJECTED, not
    # crash mid-resolve with a KeyError (adversarial-verify BUG 1: the crash-class the validator prevents).
    out = sh.transition(make_state(), [],
                        ruleset=_full_ruleset(weekly_engagement_capacity={"drone": 100000}))
    assert out["status"] == "rejected"
    assert any(code == "missing-param" for code, _ in out["rejections"])


# --- per-class WEAKEST-LINK culmination: sustained-k streaks, per class (F6) ---------------------------

def test_one_below_floor_week_does_not_fire_collapse() -> None:
    # a brutal week (no interceptors) -> every class' effective rate 0 < its floor -> each streak 1, but
    # k=3 so NOT collapsed.
    state = make_state(short=(0, 0), longi=(0, 0), pac3=(0, 0), streak=0)
    leth = status(sh.resolve(state)[0], "LETHALITY_STATUS")
    assert leth["below_floor_by_threat"]["drone"] is True
    assert leth["streak_by_threat"]["drone"] == 1 and leth["lethality_collapsed"] is False


def test_kth_consecutive_below_floor_week_fires_collapse() -> None:
    state = make_state(short=(0, 0), longi=(0, 0), pac3=(0, 0), streak=2)   # k=3: this is the 3rd week
    leth = status(sh.resolve(state)[0], "LETHALITY_STATUS")
    assert leth["streak_by_threat"]["drone"] == 3 and leth["lethality_collapsed"] is True


def test_above_floor_week_resets_the_streak() -> None:
    state = make_state(short=(100000, 0), longi=(100000, 0), pac3=(100000, 0), streak=2)
    leth = status(sh.resolve(state)[0], "LETHALITY_STATUS")
    assert leth["below_floor_by_threat"]["drone"] is False and leth["streak_by_threat"]["drone"] == 0


def test_idle_week_does_not_advance_collapse_streak() -> None:
    # adversarial-verify BUG 2: a week with NO incoming fire is not a defensive failure -> the streak must
    # not advance (an idle class can't be "below floor"; its rate is undefined, not failing).
    idle = make_state(drone=(0, 0, 0), cruise=(0, 0, 0), ballistic=(0, 0, 0), streak=2)
    leth = status(sh.resolve(idle)[0], "LETHALITY_STATUS")
    assert leth["below_floor_by_threat"]["drone"] is False
    assert leth["streak_by_threat"]["drone"] == 0 and leth["lethality_collapsed"] is False


def test_per_class_idle_reset_is_independent() -> None:
    # F6: per-class streaks are INDEPENDENT. With drone idle (no incoming) but cruise under fire and
    # failing, drone's streak RESETS while cruise's advances -- a class that stops being attacked is not
    # "collapsing", but a different class still under fire is. (Also exercises weakest-link: cruise alone
    # fires the headline.)
    state = make_state(drone=(0, 0, 0), cruise=(500, 3000, 0), ballistic=(0, 0, 0),
                       short=(0, 0), longi=(0, 0), pac3=(0, 0), streak=2)
    leth = status(sh.resolve(state)[0], "LETHALITY_STATUS")
    assert leth["streak_by_threat"]["drone"] == 0          # idle -> reset
    assert leth["streak_by_threat"]["cruise"] == 3         # under fire, 0% < 40% floor -> advanced (2->3)
    assert leth["lethality_collapsed"] is True             # weakest-link: cruise hit k=3


def test_weakest_link_one_class_collapse_fires_headline() -> None:
    # F6 (the core fix the red-team's CULM finding demanded): culmination is WEAKEST-LINK. drone is
    # well-defended (eff >> floor) but ballistic is starved below ITS floor for the kth week -> the headline
    # collapses on ballistic alone, NOT masked by drone success (the pooled metric's blind spot).
    state = make_state(drone=(1000, 50000, 0), cruise=(0, 0, 0), ballistic=(200, 5000, 0),
                       short=(1_000_000, 0), longi=(0, 0), pac3=(0, 0), streak=2)
    leth = status(sh.resolve(state)[0], "LETHALITY_STATUS")
    assert leth["below_floor_by_threat"]["drone"] is False      # drone 80% >> 50% floor
    assert leth["below_floor_by_threat"]["ballistic"] is True   # no PAC-3 -> 0% < 25% floor
    assert leth["streak_by_threat"]["ballistic"] == 3 and leth["lethality_collapsed"] is True


def test_magazine_indicator_uses_unconstrained_demand_under_starvation() -> None:
    # F6 (external red-team): under STARVATION realized consumption is pinned at/below resupply, so the OLD
    # realized-consumption net-burn falsely read "non-depleting". The indicator now uses UNCONSTRAINED
    # demand: an empty short magazine facing 1000 drones is depleting + stock_constrained, not healthy.
    state = make_state(drone=(1000, 50000, 0), cruise=(0, 0, 0), ballistic=(0, 0, 0),
                       short=(0, 50), longi=(0, 0), pac3=(0, 0), streak=0)
    mag = status(sh.resolve(state)[0], "MAGAZINE_STATUS")
    assert mag["magazine_non_depleting"] is False      # demand (1000) >> resupply (50) -> depleting
    assert mag["stock_constrained"] is True            # realized consumption (0) < demand (1000)


def test_magazine_indicator_is_independent_of_lethality_headline() -> None:
    ev = sh.resolve(make_state())[0]
    assert status(ev, "MAGAZINE_STATUS")["event_type"] == "MAGAZINE_STATUS"   # present + separate event
    assert "magazine_non_depleting" in status(ev, "MAGAZINE_STATUS")


# --- reduce is the sole constructor + strict grammar --------------------------------------------------

def test_reduce_reconstructs_the_resulting_state() -> None:
    out = sh.transition(make_state(), [], turn=0)
    rederived = sh.reduce(make_state(), out["events"])   # reduce from a fresh start == the resulting state
    assert canon.canonical_bytes(rederived["state"]) == canon.canonical_bytes(out["resulting_state"]["state"])


def test_reduce_advances_as_of_turn_via_turn_advanced() -> None:
    out = sh.transition(make_state(as_of_turn=4), [], turn=4)
    assert out["resulting_state"]["state"]["as_of_turn"] == 5


def test_reduce_rejects_unknown_event_type() -> None:
    import pytest
    with pytest.raises(sh.SalvoHetError):
        sh.reduce(make_state(), [{"event_type": "NONSENSE", "turn": 0}])


def test_reduce_rejects_unknown_threat_id() -> None:
    import pytest
    with pytest.raises(sh.SalvoHetError):
        sh.reduce(make_state(), [{"event_type": "STRIKES_LAUNCHED", "threat": "hypersonic", "count": 1}])


# --- determinism + allocation-order sensitivity -------------------------------------------------------

def test_deterministic_no_draws() -> None:
    a = sh.transition(make_state(), [], turn=0)
    b = sh.transition(make_state(), [], turn=0)
    assert a["draws"] == [] and canon.canonical_bytes(a["events"]) == canon.canonical_bytes(b["events"])


def test_allocation_order_change_preserves_conservation() -> None:
    # a scarce-interceptor week; reversing threat_order changes WHO gets the interceptors (legitimately a
    # different leak split) but must NOT crash and must preserve conservation.
    scarce = make_state(short=(300, 0), longi=(0, 0), pac3=(200, 0))
    for order in (["ballistic", "cruise", "drone"], ["drone", "cruise", "ballistic"]):
        out = sh.transition(scarce, [], ruleset=_full_ruleset(threat_order=order))
        assert out["status"] == "resolved"
        ev = evmap(out["events"])
        for t in ("drone", "cruise", "ballistic"):
            assert ev["STRIKES_LAUNCHED"][t] == ev["STRIKES_INTERCEPTED"][t] + ev["STRIKES_LEAKED"][t]


# --- PROPERTY SWEEPS (WP-E2c T4) — standing guards over the 4 properties the external red-team's NO-GO
# exposed (the WP-E2b3 fixes F3/F4/F6). The single-example regression tests above pin one counter-example
# each; these sweep a broad input space so the invariant is guarded everywhere, not just at one point. --

@pytest.mark.parametrize("retained", [1, 30, 50, 70, 99])
@pytest.mark.parametrize("threshold", [1, 7, 100, 1000, 1050])
def test_property_saturation_is_monotone_in_launches(threshold, retained) -> None:
    # F3: with abundant supply, drone intercepts must be MONOTONE NON-DECREASING as launches rise, across
    # the whole threshold/retained grid (the old step form fell off a cliff at threshold+1).
    sat = {"saturation_threshold": {t: threshold for t in ("drone", "cruise", "ballistic")},
           "saturation_retained_pct": {t: retained for t in ("drone", "cruise", "ballistic")}}
    prev = -1
    for launch in sorted({0, 1, threshold, threshold + 1, threshold + 7, 2 * threshold, 5 * threshold, 30000}):
        st = make_state(drone=(launch, 10 ** 7, 0), cruise=(0, 0, 0), ballistic=(0, 0, 0),
                        short=(10 ** 8, 0), longi=(0, 0), pac3=(0, 0))
        got = evmap(sh.resolve(st, _full_ruleset(**sat))[0])["STRIKES_INTERCEPTED"]["drone"]
        assert got >= prev, f"non-monotone at threshold={threshold} retained={retained} launch={launch}: {got}<{prev}"
        prev = got


@pytest.mark.parametrize("p", [33, 50, 65, 80, 99])
@pytest.mark.parametrize("total", [1, 2, 3, 7, 50, 137])
def test_property_grain_invariance_round_once_over_the_threat(p, total) -> None:
    # F4: a threat split across short+long (per=1 each) must intercept the ROUND-ONCE sub-pool amount,
    # invariant to HOW the split falls — sweep every short/long boundary.
    r = _full_ruleset(p_intercept_pct={"drone": p, "cruise": 65})
    expected = min(total, (total * p) // 100)               # floor ONCE over the whole sub-pool
    for short_cap in range(0, total + 1):                   # 0=all-via-long ... total=all-via-short
        st = make_state(drone=(total, 10 ** 7, 0), cruise=(0, 0, 0), ballistic=(0, 0, 0),
                        short=(short_cap, 0), longi=(10 ** 7, 0), pac3=(0, 0))
        got = evmap(sh.resolve(st, r)[0])["STRIKES_INTERCEPTED"]["drone"]
        assert got == expected, f"grain-variant at p={p} total={total} short_cap={short_cap}: {got}!={expected}"


@pytest.mark.parametrize("inv", [0, 500, 2000])
@pytest.mark.parametrize("resupply", [0, 50, 600, 1000, 5000])
def test_property_magazine_indicator_is_demand_based(resupply, inv) -> None:
    # F6: the leading indicator keys off UNCONSTRAINED demand, not realized (starved) consumption. drone
    # 1000 -> best interceptor short (per=1) -> demand 1000. non_depleting iff demand<=resupply; a starved
    # week (realized < demand) flags stock_constrained — regardless of how empty the magazine is.
    st = make_state(drone=(1000, 10 ** 7, 0), cruise=(0, 0, 0), ballistic=(0, 0, 0),
                    short=(inv, resupply), longi=(0, 0), pac3=(0, 0))
    mag = status(sh.resolve(st)[0], "MAGAZINE_STATUS")
    assert mag["magazine_non_depleting"] is (1000 <= resupply)     # demand vs resupply, NOT realized burn
    assert mag["stock_constrained"] is (inv < 1000)                # realized consumption (<=inv) < demand 1000


@pytest.mark.parametrize("collapse", ["drone", "cruise", "ballistic"])
def test_property_weakest_link_each_class_fires_alone(collapse) -> None:
    # F6: culmination is per-class WEAKEST-LINK. EACH class, collapsing alone (under fire, no interceptors,
    # streak 2->3) while the others are idle, fires the headline — none is masked, none falsely advances.
    fire = {"drone": (1000, 10 ** 7, 0), "cruise": (500, 10 ** 7, 0), "ballistic": (200, 10 ** 7, 0)}
    vols = {t: (fire[t] if t == collapse else (0, 0, 0)) for t in ("drone", "cruise", "ballistic")}
    st = make_state(drone=vols["drone"], cruise=vols["cruise"], ballistic=vols["ballistic"],
                    short=(0, 0), longi=(0, 0), pac3=(0, 0), streak=2)
    leth = status(sh.resolve(st)[0], "LETHALITY_STATUS")
    assert leth["streak_by_threat"][collapse] == 3 and leth["lethality_collapsed"] is True
    for other in ("drone", "cruise", "ballistic"):
        if other != collapse:
            assert leth["streak_by_threat"][other] == 0          # idle -> reset (not masked, not advanced)

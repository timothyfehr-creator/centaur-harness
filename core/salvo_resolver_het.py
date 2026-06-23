"""Heterogeneous salvo resolver (WP-E2b1) — deterministic, diagonal-first, integer math.

Generalizes the homogeneous WP-E2a salvo to 3 THREAT classes (drone, cruise, ballistic) vs N interceptor
TYPES, per the locked MODEL CONTRACT (centaur_engine_planning/ADJUDICATION_LEDGER.md):

  - DIAGONAL-FIRST: the CANDIDATE (observable) axis is THREAT TYPE — drone + cruise carry the candidate
    intercept rates (ASSUMED/UNCALIBRATED placeholders; E2c verdict: not separably calibratable). The
    interceptor axis is an INTERNAL magazine-accounting layer (which stock drains) with NO per-pairing rate.
    BALLISTIC leak-through is an EXOGENOUS sourced RANGE, not a candidate cell — its effective intercept rate
    derives from that range's central, never a calibratable p.
  - WEAKEST-LINK culmination: lethality-collapse when ANY threat class's effective intercept rate stays
    below ITS per-class floor for k consecutive weeks (per-class STATE-carried streaks; per-class so a
    ballistic collapse is not masked by drone success). Magazine weeks-of-supply is a separate LEADING
    INDICATOR (computed from unconstrained demand, not starved consumption), NOT a culmination trigger.
  - DETERMINISTIC (no RNG), no agent commands. Integer math (percents) -> canon-safe. reduce() is the SOLE
    constructor and needs only the events. MULTI-TURN-READY: emits TURN_ADVANCED (WP-E2b2 chains over it).

ILLUSTRATIVE / UNCALIBRATED — every parameter is an ASSUMED placeholder; asserts nothing about the real
world until the backtest (WP-E2c). Entity-id convention: ``russia_strike_<threat>`` (STRIKE_FORCE, one per
threat), ``ukraine_intc_<interceptor>`` (AIR_DEFENSE, one per interceptor type), ``ukraine_air_defense``
(AIR_DEFENSE — the network aggregate carrying the streak / culmination / indicators). Implements the
engine resolver interface {RESOLVER_ID, RESOLVER_VERSION, RULESET_VERSION, validate_all, sort_commands,
transition, reduce}.
"""
from __future__ import annotations

import copy

RESOLVER_ID = "ru_ua_salvo_heterogeneous"
RESOLVER_VERSION = "1"
RULESET_VERSION = "1"
STOCHASTIC_TERMINALS = ()        # deterministic: no draws, no stochastic terminals (turn-replay reads this)
ALLOCATION_RULE = "fixed-priority-best-first-v1"

_NETWORK = "ukraine_air_defense"  # the aggregate air-defense entity (streak + culmination + indicators)

# Default ruleset — the FLATTENED int-only form (the loader strips the {value, source} provenance tree in
# rules.yaml; sources stay in YAML). ALL values ASSUMED. ``p_intercept_pct`` holds ONLY the candidate-axis
# cells (drone, cruise); ballistic's effective rate derives from the EXOGENOUS leak range, not a p.
DEFAULT_RULESET = {
    "threats": ["drone", "cruise", "ballistic"],
    "interceptors": ["short", "long", "pac3"],
    "p_intercept_pct": {"drone": 80, "cruise": 65},        # ASSUMED/UNCALIBRATED (E2c verdict: not separably
                                                           # calibratable); ballistic EXCLUDED (exogenous)
    "per_pairing": {                                       # interceptors_per_intercept[threat][type]
        "drone": {"short": 1, "long": 1},
        "cruise": {"long": 1, "short": 2},
        "ballistic": {"pac3": 2},
    },
    "allocation_priority": {                               # best-vs-threat interceptor order per threat
        "drone": ["short", "long"],
        "cruise": ["long", "short"],
        "ballistic": ["pac3"],
    },
    "threat_order": ["ballistic", "cruise", "drone"],      # scarce-interceptor priority (VERSIONED rule)
    "weekly_engagement_capacity": {"drone": 100000, "cruise": 100000, "ballistic": 100000},
    "saturation_threshold": {"drone": 1050, "cruise": 1050, "ballistic": 1050},
    "saturation_retained_pct": {"drone": 70, "cruise": 70, "ballistic": 70},
    "ballistic_leak_floor_pct": 60,    # EXOGENOUS ASSUMED RANGE (dossier-illustrative; ballistic is HARD)
    "ballistic_leak_high_pct": 80,     # 60-80% leak = 20-40% intercept (was backwards: 65-80% intercept)
    # Per-class lethality floors (WEAKEST-LINK culmination). drone 50 LOCKED; cruise/ballistic ASSUMED
    # (contract extension, user-confirmed). Floors descend with interception difficulty; ballistic 25 sits
    # below its ~30% central nominal so the floor detects COLLAPSE, not inherent marginality.
    "lethality_floor_pct": {"drone": 50, "cruise": 40, "ballistic": 25},
    "culmination_k_weeks": 3,                              # LOCKED (3 consecutive weeks below the floor)
}


class SalvoHetError(ValueError):
    """A malformed heterogeneous-salvo state or event batch."""


def _fields(state: dict, entity_id: str) -> dict:
    for ent in state["state"]["entities"]:
        if ent["id"] == entity_id:
            return ent["fields"]
    raise SalvoHetError(f"missing entity {entity_id!r}")

def _v(state: dict, entity_id: str, field: str):
    return _fields(state, entity_id)[field]["value"]

def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)   # bool is an int subclass -> reject

def _merge(ruleset: object) -> dict:
    """Overlay a (full, flattened) ruleset on the defaults. SHALLOW — a nested override replaces the whole
    sub-dict, so a partial ruleset must supply complete nested maps (the loader / tests provide full)."""
    return {**DEFAULT_RULESET, **(ruleset or {})}

def _count(events: list, event_type: str) -> int:
    return sum(e["count"] for e in events if e["event_type"] == event_type)


def _demand(r: dict, launched: dict, threats: list, interceptors: list) -> dict:
    """Interceptors a MAGAZINE-UNCONSTRAINED week would consume under the same fixed-priority-best-first
    rule (infinite stock): saturation/capacity still bound engagements, but supply does not, so each
    threat's BEST interceptor absorbs all its (sat-capped) attempts. This is the true weekly drawdown
    pressure -> the magazine leading indicator's net-burn, so a STARVED week (realized consumption pinned
    to resupply) still reads as depleting rather than falsely 'non-depleting'. Deterministic, float-free."""
    demand = {i: 0 for i in interceptors}
    for t in r["threat_order"]:
        if t not in threats:
            continue
        sat_t = r["saturation_threshold"][t]
        if launched[t] > sat_t:
            engageable = sat_t + (r["saturation_retained_pct"][t] * (launched[t] - sat_t)) // 100
        else:
            engageable = launched[t]
        attempts = min(engageable, r["weekly_engagement_capacity"][t])
        best = r["allocation_priority"][t][0]            # infinite stock -> the best interceptor takes all
        demand[best] += attempts * r["per_pairing"][t][best]
    return demand


# --- ruleset validation (the crash-class fix: out-of-range params -> a REJECTED transition) -----------

def _validate_ruleset(r: dict) -> list:
    """Return a list of (code, msg) rejections for an out-of-range / wrong-type / incomplete ruleset.
    Run inside validate_all so a bad ruleset is a clean rejection, never a mid-resolve crash."""
    rej: list = []

    def bad(code: str, msg: str) -> None:
        rej.append((code, msg))

    threats = r.get("threats", [])
    interceptors = r.get("interceptors", [])

    for t, p in r.get("p_intercept_pct", {}).items():
        if not _is_int(p):
            bad("wrong-type", f"p_intercept_pct[{t}] must be an int; got {p!r}")
        elif not (0 <= p <= 100):
            bad("p-out-of-range", f"p_intercept_pct[{t}]={p} not in 0..100")
    for t in threats:                                    # ballistic is exogenous (no per-threat candidate p)
        if t != "ballistic" and t not in r.get("p_intercept_pct", {}):
            bad("missing-p", f"candidate-axis threat {t!r} has no p_intercept_pct")

    for t, row in r.get("per_pairing", {}).items():
        for i, per in row.items():
            if not _is_int(per):
                bad("wrong-type", f"per_pairing[{t}][{i}] must be an int; got {per!r}")
            elif per < 1:
                bad("per-out-of-range", f"per_pairing[{t}][{i}]={per} must be >= 1")

    for t, c in r.get("weekly_engagement_capacity", {}).items():
        if not _is_int(c) or c < 0:
            bad("capacity-out-of-range", f"weekly_engagement_capacity[{t}]={c} must be an int >= 0")
    for t, s in r.get("saturation_threshold", {}).items():
        if not _is_int(s) or s < 0:
            bad("saturation-threshold-out-of-range", f"saturation_threshold[{t}]={s} must be an int >= 0")
    for t, s in r.get("saturation_retained_pct", {}).items():
        if not _is_int(s) or not (0 <= s <= 100):
            bad("saturation-pct-out-of-range", f"saturation_retained_pct[{t}]={s} must be an int 0..100")
    for t in threats:   # completeness: a SHALLOW nested override must not silently drop a threat (-> KeyError)
        for name in ("weekly_engagement_capacity", "saturation_threshold", "saturation_retained_pct"):
            if t not in r.get(name, {}):
                bad("missing-param", f"{name} has no entry for threat {t!r}")

    lo, hi = r.get("ballistic_leak_floor_pct"), r.get("ballistic_leak_high_pct")
    if not _is_int(lo) or not _is_int(hi):
        bad("wrong-type", "ballistic_leak_floor_pct / ballistic_leak_high_pct must be ints")
    elif not (0 <= lo <= hi <= 100):
        bad("ballistic-leak-range-invalid", f"need 0 <= floor({lo}) <= high({hi}) <= 100")

    floors = r.get("lethality_floor_pct")
    if not isinstance(floors, dict):
        bad("lethality-floor-wrong-shape", f"lethality_floor_pct must be a per-threat dict; got {floors!r}")
    else:
        for t, lf in floors.items():
            if not _is_int(lf) or not (0 <= lf <= 100):
                bad("lethality-floor-out-of-range", f"lethality_floor_pct[{t}]={lf} must be an int 0..100")
        for t in threats:                                # completeness: every threat needs its own floor
            if t not in floors:
                bad("missing-floor", f"lethality_floor_pct has no entry for threat {t!r}")
    k = r.get("culmination_k_weeks")
    if not _is_int(k) or k < 1:
        bad("k-weeks-out-of-range", f"culmination_k_weeks={k} must be an int >= 1")

    for t in threats:
        prio = r.get("allocation_priority", {}).get(t)
        if not prio:
            bad("missing-allocation", f"threat {t!r} has no allocation_priority")
            continue
        for i in prio:
            if i not in interceptors:
                bad("unknown-interceptor-id", f"allocation_priority[{t}] references unknown interceptor {i!r}")
            elif i not in r.get("per_pairing", {}).get(t, {}):
                bad("missing-per", f"per_pairing[{t}] has no entry for interceptor {i!r}")
    return rej


# --- interface ----------------------------------------------------------------------------------------

def validate_all(commands: list, start_state: dict, ruleset: object = None):
    """Return (accepted, rejections). No agent commands; an out-of-range ruleset is REJECTED (no crash)."""
    rej: list = []
    if commands:
        rej.append(("unexpected-command", "WP-E2b1 heterogeneous salvo accepts no agent commands"))
    rej.extend(_validate_ruleset(_merge(ruleset)))
    return [], rej

def sort_commands(accepted: list) -> list:
    return list(accepted)   # always empty


def resolve(start_state: dict, ruleset: object = None, turn: int = 0):
    """One week, deterministic, diagonal-first. Events encode the outcome (incl. the streak/culmination,
    decided here with the rule so reduce needs no rule)."""
    r = _merge(ruleset)
    threats, interceptors = r["threats"], r["interceptors"]

    launched = {t: min(_v(start_state, "russia_strike_" + t, "weekly_launch"),
                       _v(start_state, "russia_strike_" + t, "strike_inventory")) for t in threats}
    production = {t: _v(start_state, "russia_strike_" + t, "weekly_production") for t in threats}
    magazine = {i: _v(start_state, "ukraine_intc_" + i, "interceptor_inventory") for i in interceptors}
    resupply = {i: _v(start_state, "ukraine_intc_" + i, "weekly_resupply") for i in interceptors}

    # Effective intercept pct per threat: the candidate-axis p for drone/cruise; BALLISTIC from the exogenous
    # range central (100 - mean leak), never a candidate cell.
    ballistic_leak_central = (r["ballistic_leak_floor_pct"] + r["ballistic_leak_high_pct"]) // 2
    p_used = {t: (100 - ballistic_leak_central if t == "ballistic" else r["p_intercept_pct"][t])
              for t in threats}

    # Allocation (fixed-priority-best-first-v1) + saturation cap; shared magazines drain in threat_order.
    magazine_remaining = dict(magazine)
    fired: dict = {t: {} for t in threats}      # attempts assigned to (t, i)
    used: dict = {t: {} for t in threats}       # interceptors physically fired (= attempts * per)
    for t in r["threat_order"]:
        if t not in threats:
            continue
        prio = r["allocation_priority"][t]
        supply_ceiling = sum(magazine_remaining[i] // r["per_pairing"][t][i] for i in prio)
        # Saturation degrades the volume the defense can ENGAGE (a tracking/launch limit, not a supply
        # limit). MONOTONE + continuous at the threshold T: at/below T it engages all; above T each extra
        # launch adds only retained% of an engagement, so attempts never DROP as launches rise (the old
        # ``base_cap * retained`` step was discontinuous/non-monotonic: 1050->1050 but 1051->735). Then
        # bound by the magazine (supply) and the hard weekly engagement capacity.
        sat_t = r["saturation_threshold"][t]
        if launched[t] > sat_t:
            engageable = sat_t + (r["saturation_retained_pct"][t] * (launched[t] - sat_t)) // 100
        else:
            engageable = launched[t]
        attempted_cap = min(engageable, supply_ceiling, r["weekly_engagement_capacity"][t])
        remaining = attempted_cap
        for i in prio:
            per = r["per_pairing"][t][i]
            take = min(remaining, magazine_remaining[i] // per)
            fired[t][i] = take
            used[t][i] = take * per
            magazine_remaining[i] -= take * per
            remaining -= take
            if remaining == 0:
                break

    # Per-threat-SUBPOOL capped intercept: sum the attempts across interceptor types, apply the THREAT
    # rate, and floor ONCE (NOT per (t,i) cell -- per-cell flooring discards fractional kills when a threat
    # is split across types, e.g. 2 launched via two 80% types -> floor(0.8)+floor(0.8)=0 vs round-once 1).
    # The remaining sub-1 per-WEEK flooring residual is a documented, deferred minor bias (systematic-down,
    # negligible at realistic salvo volumes of hundreds/wk; only material at <~5 engagements/threat/week).
    intercepted = {t: min(launched[t], (sum(fired[t].values()) * p_used[t]) // 100) for t in threats}
    leaked = {t: launched[t] - intercepted[t] for t in threats}          # >= 0 by the cap; NO max(0,..)
    # Consumed tracked SEPARATELY and NOT capped by launched -> over-firing still burns the magazine.
    consumed = {i: sum(used[t].get(i, 0) for t in threats) for i in interceptors}

    launched_tot, intercepted_tot = sum(launched.values()), sum(intercepted.values())
    effective_intercept_pct = (intercepted_tot * 100) // launched_tot if launched_tot > 0 else 0

    # Magazine LEADING INDICATOR (separate from culmination). The net-burn uses UNCONSTRAINED weekly DEMAND
    # (what a magazine-free week would consume), NOT the realized (starved) consumption -- else under
    # starvation realized falls toward resupply and the sentinel falsely reads "non-depleting" while the
    # defense is actually losing the magazine race (the F6 bug the committed records 0005/0006 exhibited).
    demand = _demand(r, launched, threats, interceptors)
    magazine_after = {i: magazine[i] - consumed[i] + resupply[i] for i in interceptors}   # realized drawdown
    net_burn = {i: demand[i] - resupply[i] for i in interceptors}                          # demand vs resupply
    depleting = [i for i in interceptors if net_burn[i] > 0]
    magazine_non_depleting = not depleting
    weeks_remaining = 0 if magazine_non_depleting else min(magazine_after[i] // net_burn[i] for i in depleting)
    magazine_depleted = any(magazine_after[i] <= 0 for i in interceptors)
    stock_constrained = any(consumed[i] < demand[i] for i in interceptors)    # realized < demand -> starved

    # CULMINATION = lethality-collapse, WEAKEST-LINK over all threat classes: any class whose effective
    # intercept rate stays below ITS floor for k consecutive weeks. Per-class (not pooled) so a ballistic-
    # defense collapse is NOT masked by drone success. An IDLE class (no incoming fire that week) has an
    # undefined -- not failing -- rate, so it does not advance (and resets) its streak. Per the locked
    # contract, magazine depth is a LEADING INDICATOR, not a trigger -> the prior pooled inventory OR-limb
    # is DROPPED (it fired culminated on turn 0 and could mask a single-class collapse).
    # KNOWN LIMITATION (documented, deferred): per-class idle-reset is LESS sensitive than the aggregate to
    # an adversary that ALTERNATES which class it saturates -- no single class then sustains k consecutive
    # below-floor weeks. Acceptable for this ILLUSTRATIVE model; a future WP could add a combined or
    # decaying streak if alternating-saturation regimes become decision-relevant.
    floors = r["lethality_floor_pct"]
    effective_pct = {t: (intercepted[t] * 100) // launched[t] if launched[t] > 0 else 0 for t in threats}
    old_streak = {t: _v(start_state, _NETWORK, "streak_" + t) for t in threats}
    below_floor = {t: launched[t] > 0 and effective_pct[t] < floors[t] for t in threats}
    new_streak = {t: (old_streak[t] + 1) if below_floor[t] else 0 for t in threats}
    lethality_collapsed = any(new_streak[t] >= r["culmination_k_weeks"] for t in threats)
    culminated = lethality_collapsed

    # Ballistic exogenous-rate SENSITIVITY band. NOT decorative: it holds the magazine-constrained attempts
    # FIXED and varies the leak rate across [floor, central, high], so the leaked band BRACKETS the
    # deterministic central count by construction (more intercept -> less leak, same flooring direction) and
    # it propagates into a reported effective-rate band + a culmination-verdict indeterminacy flag. It does
    # NOT alter the committed deterministic counts (those use the central rate). Float-free: the intercept
    # path uses //, so no ceil/float is needed to keep low <= central <= high.
    lb = launched.get("ballistic", 0)
    ball_attempts = sum(fired.get("ballistic", {}).values())

    def _ball_intercept(intercept_pct: int) -> int:
        return min(lb, (ball_attempts * intercept_pct) // 100)

    intc_ball_best = _ball_intercept(100 - r["ballistic_leak_floor_pct"])    # low leak  -> most intercepts
    intc_ball_worst = _ball_intercept(100 - r["ballistic_leak_high_pct"])    # high leak -> fewest intercepts
    leak_low, leak_high = lb - intc_ball_best, lb - intc_ball_worst          # low <= central <= high
    eff_ball_high = (intc_ball_best * 100) // lb if lb > 0 else 0            # best-case effective rate
    eff_ball_low = (intc_ball_worst * 100) // lb if lb > 0 else 0           # worst-case effective rate
    # Does the band straddle the ballistic floor? (output-only -- never feeds the deterministic streak,
    # which uses the central count alone.) Uses the per-class ballistic floor.
    ball_floor = floors["ballistic"]
    ballistic_verdict_indeterminate = (lb > 0 and eff_ball_low < ball_floor <= eff_ball_high)

    events: list = []
    seq = [0]

    def emit(**d):
        seq[0] += 1
        events.append({"event_id": f"ev-{seq[0]:03d}", "turn": turn, **d})

    for t in threats:
        emit(event_type="STRIKES_LAUNCHED", threat=t, count=launched[t])
    for i in interceptors:
        emit(event_type="INTERCEPTS_EXPENDED", interceptor_type=i, count=consumed[i])
    for t in threats:
        emit(event_type="STRIKES_INTERCEPTED", threat=t, count=intercepted[t])
    for t in threats:
        emit(event_type="STRIKES_LEAKED", threat=t, count=leaked[t])
    for t in threats:
        emit(event_type="RESUPPLY_STRIKE", threat=t, count=production[t])
    for i in interceptors:
        emit(event_type="RESUPPLY_INTERCEPTOR", interceptor_type=i, count=resupply[i])
    emit(event_type="BALLISTIC_LEAK_BAND", leak_low=leak_low, leak_high=leak_high,
         eff_pct_low=eff_ball_low, eff_pct_high=eff_ball_high,
         verdict_indeterminate=ballistic_verdict_indeterminate)
    emit(event_type="LETHALITY_STATUS", effective_intercept_pct=effective_intercept_pct,
         effective_pct_by_threat=effective_pct, below_floor_by_threat=below_floor,
         streak_by_threat=new_streak, lethality_collapsed=lethality_collapsed)
    emit(event_type="MAGAZINE_STATUS", magazine_non_depleting=magazine_non_depleting,
         weeks_remaining=weeks_remaining, magazine_depleted=magazine_depleted,
         stock_constrained=stock_constrained)
    emit(event_type="CULMINATION_STATUS", culminated=culminated)
    emit(event_type="TURN_ADVANCED", to_turn=turn + 1)
    return events, []   # no draws (deterministic)


def reduce(start_state: dict, events: list) -> dict:
    """new_state := reduce(start_state, events). SOLE constructor; needs only the events."""
    state = copy.deepcopy(start_state)
    for ev in events:
        kind = ev["event_type"]
        if kind == "STRIKES_LAUNCHED":
            f = _fields(state, "russia_strike_" + ev["threat"])
            f["strike_inventory"]["value"] -= ev["count"]
            f["cumulative_launched"]["value"] += ev["count"]
        elif kind == "STRIKES_LEAKED":
            _fields(state, "russia_strike_" + ev["threat"])["cumulative_leaked"]["value"] += ev["count"]
        elif kind == "RESUPPLY_STRIKE":
            _fields(state, "russia_strike_" + ev["threat"])["strike_inventory"]["value"] += ev["count"]
        elif kind == "INTERCEPTS_EXPENDED":
            _fields(state, "ukraine_intc_" + ev["interceptor_type"])["interceptor_inventory"]["value"] -= ev["count"]
        elif kind == "RESUPPLY_INTERCEPTOR":
            _fields(state, "ukraine_intc_" + ev["interceptor_type"])["interceptor_inventory"]["value"] += ev["count"]
        elif kind == "STRIKES_INTERCEPTED":
            _fields(state, _NETWORK)["cumulative_intercepted"]["value"] += ev["count"]
        elif kind == "LETHALITY_STATUS":
            net = _fields(state, _NETWORK)
            for t, s in ev["streak_by_threat"].items():       # per-class weakest-link streaks
                net["streak_" + t]["value"] = s
            net["lethality_collapsed"]["value"] = ev["lethality_collapsed"]
        elif kind == "MAGAZINE_STATUS":
            net = _fields(state, _NETWORK)
            net["magazine_non_depleting"]["value"] = ev["magazine_non_depleting"]
            net["magazine_weeks_remaining"]["value"] = ev["weeks_remaining"]
            net["magazine_stock_constrained"]["value"] = ev["stock_constrained"]
        elif kind == "CULMINATION_STATUS":
            _fields(state, _NETWORK)["culminated"]["value"] = ev["culminated"]
        elif kind == "TURN_ADVANCED":
            state["state"]["as_of_turn"] = ev["to_turn"]
        elif kind == "BALLISTIC_LEAK_BAND":
            pass    # reporting-only (the exogenous sensitivity band); no state mutation
        else:
            raise SalvoHetError(f"unknown event_type {kind!r}")
    return state


def transition(start_state: dict, commands: list, *, master_seed: int = 0, turn: int = 0,
               ruleset: object = None) -> dict:
    """validate -> resolve -> reduce -> invariant check. No RNG (master_seed unused). A bad ruleset or any
    command -> reject (no record). Post-reduce invariants fail CLOSED (raise) on a math/grammar violation."""
    accepted, rejections = validate_all(commands, start_state, ruleset)
    if rejections:
        return {"status": "rejected", "rejections": rejections,
                "events": [], "draws": [], "resulting_state": start_state}
    events, draws = resolve(start_state, ruleset, turn=turn)
    new_state = reduce(start_state, events)

    r = _merge(ruleset)
    threats, interceptors = r["threats"], r["interceptors"]
    # conservation (total) + per-threat overkill (intercepted_t <= launched_t)
    if _count(events, "STRIKES_LAUNCHED") != _count(events, "STRIKES_INTERCEPTED") + _count(events, "STRIKES_LEAKED"):
        raise SalvoHetError("conservation-violation (launched != intercepted + leaked)")
    launched_t = {e["threat"]: e["count"] for e in events if e["event_type"] == "STRIKES_LAUNCHED"}
    for e in events:
        if e["event_type"] == "STRIKES_INTERCEPTED" and e["count"] > launched_t.get(e["threat"], 0):
            raise SalvoHetError(f"overkill-violation (intercepted_{e['threat']} > launched)")
    # per-entity non-negativity
    for t in threats:
        if _v(new_state, "russia_strike_" + t, "strike_inventory") < 0:
            raise SalvoHetError(f"non-negativity-violation (russia_strike_{t}.strike_inventory)")
    for i in interceptors:
        if _v(new_state, "ukraine_intc_" + i, "interceptor_inventory") < 0:
            raise SalvoHetError(f"non-negativity-violation (ukraine_intc_{i}.interceptor_inventory)")
    # turn-advance: exactly one TURN_ADVANCED, to_turn == as_of_turn + 1
    advances = [e for e in events if e["event_type"] == "TURN_ADVANCED"]
    if len(advances) != 1 or advances[0]["to_turn"] != start_state["state"]["as_of_turn"] + 1:
        raise SalvoHetError("turn-advance-violation")
    return {"status": "resolved", "events": events, "draws": draws, "resulting_state": new_state}

"""Homogeneous salvo resolver (WP-E2a) — deterministic Hughes salvo, weekly, integer math.

ILLUSTRATIVE / UNCALIBRATED: one aggregated Russian strike pool vs one Ukrainian interceptor pool,
one week. EVERY parameter is an ASSUMED placeholder supplied via the ruleset (see WP-E2_PLAN.md); the
model asserts nothing about the real world until the backtest (WP-E2c). `p_intercept` is an integer
PERCENT so the engine stays float-free (canon-safe). No RNG (deterministic expected values). reduce()
is the SOLE state constructor and needs only the events. Implements the engine resolver interface
{RESOLVER_ID, RESOLVER_VERSION, RULESET_VERSION, validate_all, sort_commands, transition, reduce}.
"""
from __future__ import annotations

import copy

RESOLVER_ID = "ru_ua_salvo_homogeneous"
RESOLVER_VERSION = "1"
RULESET_VERSION = "1"
STOCHASTIC_TERMINALS = ()   # deterministic salvo: no draws, no stochastic terminals (turn-replay reads this)

# Default params (ALL ASSUMED — needs calibration). Integer-only (p as a percent) to stay canon-safe.
DEFAULT_RULESET = {
    "p_intercept_pct": 80,            # ASSUMED — CSIS drone intercept ~75-90%; placeholder
    "interceptors_per_intercept": 1,  # ASSUMED — homogeneous proof
    "culmination_threshold": 120,     # ASSUMED — inventory-based placeholder; the inventory-vs-lethality
                                      #           definition is an OPEN DECISION (see WP-E2_PLAN.md)
}

_FORCE = "russia_strikeforce"
_DEF = "ukraine_air_defense"


class SalvoError(ValueError):
    """A malformed salvo state or event batch."""


def _fields(state: dict, entity_id: str) -> dict:
    for ent in state["state"]["entities"]:
        if ent["id"] == entity_id:
            return ent["fields"]
    raise SalvoError(f"missing entity {entity_id!r}")

def _v(state: dict, entity_id: str, field: str) -> int:
    return _fields(state, entity_id)[field]["value"]


# --- interface: E2a is a deterministic week with NO agent commands -------------------

def validate_all(commands: list, start_state: dict, ruleset: object = None):
    """Return (accepted, rejections). WP-E2a takes NO commands (the week is deterministic from
    state + ruleset); any command is rejected (reject-all-or-resolve, zero mutation)."""
    if commands:
        return [], [("unexpected-command", "WP-E2a homogeneous salvo accepts no agent commands")]
    return [], []

def sort_commands(accepted: list) -> list:
    return list(accepted)   # always empty for E2a


def resolve(start_state: dict, ruleset: object = None, turn: int = 0):
    """One week, deterministic. The resolver reads the ruleset (p_intercept etc.); events encode the
    outcome (incl. the culmination flag, decided here with the threshold so reduce needs no rule)."""
    r = {**DEFAULT_RULESET, **(ruleset or {})}
    pct, per, threshold = r["p_intercept_pct"], r["interceptors_per_intercept"], r["culmination_threshold"]

    launch_rate = _v(start_state, _FORCE, "weekly_launch")
    strike_inv = _v(start_state, _FORCE, "strike_inventory")
    production = _v(start_state, _FORCE, "weekly_production")
    interceptor_inv = _v(start_state, _DEF, "interceptor_inventory")
    resupply = _v(start_state, _DEF, "weekly_resupply")

    launched = min(launch_rate, strike_inv)
    attempted = min(launched, interceptor_inv // per)
    intercepted = (attempted * pct) // 100          # integer expected-value
    leaked = launched - intercepted
    consumed = attempted * per
    culminated = (interceptor_inv - consumed + resupply) < threshold   # decided WITH the rule

    events = [
        {"event_id": "ev-001", "turn": turn, "event_type": "STRIKES_LAUNCHED", "count": launched},
        {"event_id": "ev-002", "turn": turn, "event_type": "INTERCEPTS_EXPENDED", "count": consumed},
        {"event_id": "ev-003", "turn": turn, "event_type": "STRIKES_INTERCEPTED", "count": intercepted},
        {"event_id": "ev-004", "turn": turn, "event_type": "STRIKES_LEAKED", "count": leaked},
        {"event_id": "ev-005", "turn": turn, "event_type": "RESUPPLY", "side": "russia", "count": production},
        {"event_id": "ev-006", "turn": turn, "event_type": "RESUPPLY", "side": "ukraine", "count": resupply},
        {"event_id": "ev-007", "turn": turn, "event_type": "CULMINATION_STATUS", "culminated": culminated},
    ]
    return events, []   # no draws (deterministic)


def reduce(start_state: dict, events: list) -> dict:
    """new_state := reduce(start_state, events). SOLE constructor; needs only the events."""
    state = copy.deepcopy(start_state)
    force = _fields(state, _FORCE)
    defense = _fields(state, _DEF)
    for ev in events:
        kind = ev["event_type"]
        if kind == "STRIKES_LAUNCHED":
            force["strike_inventory"]["value"] -= ev["count"]
            force["cumulative_launched"]["value"] += ev["count"]
        elif kind == "INTERCEPTS_EXPENDED":
            defense["interceptor_inventory"]["value"] -= ev["count"]
        elif kind == "STRIKES_INTERCEPTED":
            defense["cumulative_intercepted"]["value"] += ev["count"]
        elif kind == "STRIKES_LEAKED":
            force["cumulative_leaked"]["value"] += ev["count"]
        elif kind == "RESUPPLY":
            if ev["side"] == "russia":
                force["strike_inventory"]["value"] += ev["count"]
            elif ev["side"] == "ukraine":
                defense["interceptor_inventory"]["value"] += ev["count"]
            else:
                raise SalvoError(f"unknown resupply side {ev['side']!r}")
        elif kind == "CULMINATION_STATUS":
            defense["culminated"]["value"] = ev["culminated"]
        else:
            raise SalvoError(f"unknown event_type {kind!r}")
    return state


def _count(events: list, event_type: str) -> int:
    return sum(e["count"] for e in events if e["event_type"] == event_type)


def transition(start_state: dict, commands: list, *, master_seed: int = 0, turn: int = 0,
               ruleset: object = None) -> dict:
    """validate -> resolve -> reduce -> invariant check. No RNG (master_seed unused). A command -> reject."""
    accepted, rejections = validate_all(commands, start_state, ruleset)
    if rejections:
        return {"status": "rejected", "rejections": rejections,
                "events": [], "draws": [], "resulting_state": start_state}
    events, draws = resolve(start_state, ruleset, turn=turn)
    new_state = reduce(start_state, events)
    # invariants: launched == intercepted + leaked; inventories non-negative
    if _count(events, "STRIKES_LAUNCHED") != _count(events, "STRIKES_INTERCEPTED") + _count(events, "STRIKES_LEAKED"):
        raise SalvoError("conservation-violation (launched != intercepted + leaked)")
    if _v(new_state, _FORCE, "strike_inventory") < 0 or _v(new_state, _DEF, "interceptor_inventory") < 0:
        raise SalvoError("non-negativity-violation")
    return {"status": "resolved", "events": events, "draws": draws, "resulting_state": new_state}

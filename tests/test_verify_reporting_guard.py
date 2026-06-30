"""Honesty-reporting guards for scripts/verify.py (WP-A1b §3.4).

verify.py must keep declaring -- in the NOT_YET_IMPLEMENTED list that BOTH draft and release print -- that
(a) the agent transcript / judge / ENSEMBLE layers are NO-GO'd (a decision-facing AI-playthrough transcript
is false-validity), and (b) the @live model lane is non-deterministic and OUT of the green gate (a model is
never re-called IN THE GATE -- CI/pytest only replay committed bytes). These guards fail loudly if a future
edit silently upgrades either claim.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import verify  # noqa: E402

_NYI = "\n".join(verify.NOT_YET_IMPLEMENTED).lower()


def test_ensemble_layer_stays_no_go() -> None:
    # the verbatim load-bearing phrases of the ensemble/transcript NO-GO must survive (§3.4).
    assert "ensemble" in _NYI
    assert "no-go" in _NYI
    assert "machine log only, never a forecast" in _NYI


def test_live_lane_reported_out_of_gate_not_certified() -> None:
    # The @live lane now EXISTS but is non-deterministic, so the report must say it is OUT of the green gate
    # and that the GATE never re-calls a model (replay-scoped) -- never that a live call is gated/certified.
    assert "@live" in _NYI
    assert "out of the green gate" in _NYI
    assert "never re-called in the gate" in _NYI


def test_no_yet_unimplemented_entry_claims_it_passed() -> None:
    # a NOT_YET_IMPLEMENTED entry must never read as done (no "is implemented"/"now passes" creep).
    for phrase in ("is implemented", "now passes", "fully built", "is complete"):
        assert phrase not in _NYI

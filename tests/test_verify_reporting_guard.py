"""Honesty-reporting guards for scripts/verify.py (WP-A1b §3.4).

verify.py must keep declaring -- in the NOT_YET_IMPLEMENTED list that BOTH draft and release print -- that
(a) the agent transcript / judge / ENSEMBLE layers are NO-GO'd (a decision-facing AI-playthrough transcript
is false-validity), and (b) the LIVE model call itself is unbuilt (no model is ever called; the substrate
only replays committed bytes). These guards fail loudly if a future edit silently upgrades either claim.
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


def test_live_call_itself_is_still_declared_unbuilt() -> None:
    # A1b built the OFFLINE machinery, NOT the live call. The report must still say no model is called.
    assert "no model is ever called" in _NYI
    assert "@live lane" in _NYI or "live agent model call" in _NYI


def test_no_yet_unimplemented_entry_claims_it_passed() -> None:
    # a NOT_YET_IMPLEMENTED entry must never read as done (no "is implemented"/"now passes" creep).
    for phrase in ("is implemented", "now passes", "fully built", "is complete"):
        assert phrase not in _NYI

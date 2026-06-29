"""WP-A1b §3.4/§4.4 guard: the committed LIVE CAPTURE_ARTIFACT must lead with its four honesty disclosures
verbatim, so a later edit cannot quietly upgrade a single non-deterministic capture into a forecast."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE = REPO_ROOT / "examples" / "contested_logistics_agents_live"

# Verbatim phrases that must survive in the committed disclosure (README + scenario.yaml).
_REQUIRED = (
    "not a model, not a sample, not analysis",                         # CAPTURE_ARTIFACT
    "memoryless one-shot reasoner",                                    # memoryless
    "must not be presented as a continuous strategist",               # memoryless
    "attestation by the runner, not a proof",                         # authenticity
    "internal CONSISTENCY, not byte AUTHENTICITY",                     # authenticity residual
    "n equals 1",                                                     # sample size
)


def test_capture_artifact_disclosures_present_verbatim() -> None:
    if not LIVE.is_dir():
        import pytest
        pytest.skip("live capture scenario not present (built by the @live run)")
    # collapse whitespace so a markdown line-wrap inside a phrase does not defeat the verbatim check
    readme = " ".join((LIVE / "README.md").read_text(encoding="utf-8").split())
    scenario = (LIVE / "scenario.yaml").read_text(encoding="utf-8")
    for phrase in _REQUIRED:
        assert phrase in readme, f"missing disclosure in README: {phrase!r}"
    assert "CAPTURE_ARTIFACT" in scenario and "label: CAPTURE_ARTIFACT" in scenario


def test_live_scenario_is_not_in_the_attestation_tier() -> None:
    # a CAPTURE_ARTIFACT carries no signoff/review/calibration (it is not analysis to be attested)
    if not LIVE.is_dir():
        import pytest
        pytest.skip("live capture scenario not present")
    for forbidden in ("signoff.yaml", "review.yaml", "calibration.yaml", "calibration_feasibility.yaml"):
        assert not (LIVE / forbidden).exists(), f"a CAPTURE_ARTIFACT must not carry {forbidden}"


def test_committed_live_capture_binds_under_provenance() -> None:
    # M1 R1: the committed first live capture (rendered with the frozen-v1 template) must still BIND -- pinned
    # in pytest so a silent break/deletion is caught here, not only by the release-time provenance sweep.
    if not LIVE.is_dir():
        import pytest
        pytest.skip("live capture scenario not present")
    gate = REPO_ROOT / "scripts" / "validate_agent_provenance.py"
    r = subprocess.run([sys.executable, str(gate), "--scenario-dir", str(LIVE)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "2 step(s) bound" in r.stdout

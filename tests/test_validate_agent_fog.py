"""Behavior tests for scripts/validate_agent_fog.py (the differential fog no-leak gate, WP-A1a).

The committed agent records must leak nothing; a hidden value smuggled into a public field is caught by
the canary; and if the projector ever regressed to leak a ROUTE_SECRET, the structural guard fires.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TWO_P = REPO_ROOT / "examples" / "contested_logistics_agents_2p"
GATE = REPO_ROOT / "scripts" / "validate_agent_fog.py"
PROV = REPO_ROOT / "scripts" / "validate_agent_provenance.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_agent_fog as vaf  # noqa: E402
from canon import canonical_digest  # noqa: E402


def _rec() -> dict:
    return json.loads((TWO_P / "run" / "turns" / "0000.json").read_text())


def _codes(problems) -> list[str]:
    return [c for c, _, _ in problems]


def test_committed_agent_records_leak_nothing() -> None:
    assert vaf._leak_problems(_rec(), "x") == []


def test_two_player_record_has_a_draw_and_two_commands() -> None:
    rec = _rec()
    assert len(rec["command_batch"]) == 2 and len(rec["draw_records"]) == 1
    assert any(e["event_type"] == "SUPPLY_LOST" for e in rec["event_batch"])


def test_canary_catches_a_hidden_value_smuggled_into_a_public_field() -> None:
    rec = _rec()
    raw_uint = rec["draw_records"][0]["raw_uint"]      # a hidden 64-bit draw value
    leaked = copy.deepcopy(rec)
    for ent in leaked["resulting_state"]["state"]["entities"]:
        if ent["id"] == "blue_supply":                 # public entity -> visible to BLUE
            ent["fields"]["origin"]["value"] = raw_uint
    assert "hidden-value-verbatim" in _codes(vaf._leak_problems(leaked, "x"))


def test_structural_guard_fires_if_the_projector_regresses(monkeypatch) -> None:
    # if a future projector change leaked a ROUTE_SECRET into an agent view, the gate must catch it
    def leaky(viewer, rec, agent_ids=None):
        state = {"schema_version": "1.0", "state": {"as_of_turn": 1, "entities": [
            {"type": "ROUTE_SECRET", "id": "route_secret:r1", "fields": {}}]}}
        return {"viewer": viewer, "turn": rec["turn"], "state": state, "events": [],
                "projection_digest": canonical_digest({"state": state, "events": []})}
    monkeypatch.setattr(vaf.ep, "project_turn_record", leaky)
    assert "route-secret-in-view" in _codes(vaf._leak_problems(_rec(), "x"))


def test_draw_field_guard_fires_if_a_short_draw_value_leaks_onto_an_event(monkeypatch) -> None:
    # a projector regression that surfaced d100 (a short int the canary skips) on a view event is caught
    def leaky(viewer, rec, agent_ids=None):
        state = {"schema_version": "1.0", "state": {"as_of_turn": 1, "entities": []}}
        return {"viewer": viewer, "turn": rec["turn"],
                "state": state, "events": [{"event_type": "SUPPLY_LOST", "d100": 11}],
                "projection_digest": canonical_digest({"state": state, "events": []})}
    monkeypatch.setattr(vaf.ep, "project_turn_record", leaky)
    assert "draw-field-in-view" in _codes(vaf._leak_problems(_rec(), "x"))


def test_gate_vacuous_when_no_agent_records(tmp_path: Path) -> None:
    r = subprocess.run([sys.executable, str(GATE), "--scenario-dir", str(tmp_path)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "no agent records" in r.stdout


def test_two_player_scenario_binds_under_provenance() -> None:
    r = subprocess.run([sys.executable, str(PROV), "--scenario-dir", str(TWO_P)],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "2 step(s) bound" in r.stdout


def test_gate_cli_passes_on_committed_records() -> None:
    r = subprocess.run([sys.executable, str(GATE)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "hidden state never entered any view" in r.stdout

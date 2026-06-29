"""Tests for core/prompt_templates.py (WP-A1b §2.2 — the pure template registry, purity, sentinel scan)."""
from __future__ import annotations

import copy

import prompt_templates as pt
from canon import canonical_bytes
from engine_projection import project_turn_record

PV = pt.A1B_PROMPT_VERSION


def _full_state(*, threshold: int, blue_origin: int = 100) -> dict:
    """A contested-logistics full state with a SECRET block_threshold in a ROUTE_SECRET entity."""
    return {"schema_version": "1.0", "state": {"as_of_turn": 0, "entities": [
        {"id": "blue_supply", "type": "FORCE", "fields": {
            "origin": {"value": blue_origin, "unit": "units"}, "in_transit": {"value": 0, "unit": "units"},
            "delivered": {"value": 0, "unit": "units"}, "loss_sink": {"value": 0, "unit": "units"}}},
        {"id": "route:r1", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": True, "unit": "bool"}}},
        {"id": "route_secret:r1", "type": "ROUTE_SECRET", "fields": {
            "subject_route": {"value": "r1", "unit": "id"},
            "block_threshold": {"value": threshold, "unit": "d100"}}}]}}


def _fog_view(*, threshold: int, blue_origin: int = 100) -> dict:
    tr = {"turn": 0, "resulting_state": _full_state(threshold=threshold, blue_origin=blue_origin),
          "event_batch": []}
    return project_turn_record("BLUE", tr)


# --- determinism / no clock|nonce -------------------------------------------------------------------

def test_render_is_deterministic_no_clock_or_nonce() -> None:
    view = _fog_view(threshold=73)
    a = pt.canonical_request_bytes(PV, view)
    b = pt.canonical_request_bytes(PV, view)
    assert a == b and a == canonical_bytes(pt.render_request_envelope(PV, view))


def test_envelope_shape_is_the_a1b_contract() -> None:
    env = pt.render_request_envelope(PV, _fog_view(threshold=73))
    assert env["model"] == "claude-opus-4-8" and env["max_tokens"] == 1024
    assert env["tool_choice"]["type"] == "tool" and env["tool_choice"]["name"] == "submit_command"
    assert [t["name"] for t in env["tools"]] == ["submit_command"]
    assert "thinking" not in env and "temperature" not in env and "top_p" not in env  # amend 8 + un-spellable
    assert env["messages"][0]["role"] == "user"


# --- content-pinned version (Fork B) ----------------------------------------------------------------

def test_prompt_version_is_content_pinned() -> None:
    assert set(pt.APPROVED_PROMPT_VERSIONS) <= set(pt.PROMPT_TEMPLATES)   # approved => registered
    assert PV.startswith("ptmpl-")
    for field in ("system", "user_prefix"):            # the fixed system prose AND the user-instruction prefix
        edited = copy.deepcopy(pt.PROMPT_TEMPLATES[PV])
        edited[field] = edited[field] + " (extra clause)"
        assert pt.prompt_version_of(edited) != PV, f"editing {field} must move the version (amendment 4)"


def test_frozen_v1_pins_the_historical_capture_version() -> None:
    # the committed FIRST live capture was rendered with the frozen-v1 prompt; pin its version in pytest so a
    # silent edit of _SYSTEM_PROSE_V1_FROZEN is caught here, not only by the release-time provenance sweep (M1 R1).
    assert pt._A1B_PROMPT_VERSION_V1 == "ptmpl-8a6e10b1240e09ca"
    assert pt._A1B_PROMPT_VERSION_V1 in pt.PROMPT_TEMPLATES
    assert pt._A1B_PROMPT_VERSION_V1 in pt.APPROVED_PROMPT_VERSIONS
    assert pt.A1B_PROMPT_VERSION != pt._A1B_PROMPT_VERSION_V1          # current (with the supply rule) is distinct


def test_unregistered_version_refuses_to_render() -> None:
    import pytest
    with pytest.raises(KeyError):
        pt.render_request_envelope("ptmpl-deadbeefdeadbeef", _fog_view(threshold=73))


# --- the differential-PURITY invariant (§2.2 leg 3 — "a leaky template binds green") ----------------

def test_fixed_part_is_invariant_across_secret_and_public_variation() -> None:
    # EVERY approved version must be pure (the versioned registry now holds >1; A1b landing-review residual).
    for pv in pt.APPROVED_PROMPT_VERSIONS:
        # vary the SECRET (block_threshold): the whole request is byte-identical (fog excludes the secret)...
        full_a = pt.canonical_request_bytes(pv, _fog_view(threshold=1))
        full_b = pt.canonical_request_bytes(pv, _fog_view(threshold=99))
        assert full_a == full_b, f"secret leaked into the request for {pv}"
        # ...and across a MATERIALLY DIFFERENT public view, the FIXED part (system+tools+pins) is unchanged,
        # proving the fixed part is a pure function of prompt_version alone (no view/secret access).
        fixed_1 = canonical_bytes(pt.fixed_part(pt.render_request_envelope(pv, _fog_view(threshold=5, blue_origin=100))))
        fixed_2 = canonical_bytes(pt.fixed_part(pt.render_request_envelope(pv, _fog_view(threshold=5, blue_origin=7))))
        assert fixed_1 == fixed_2, f"fixed part not invariant for {pv}"


# --- the secret-sentinel request scan (amendment 5) -------------------------------------------------

def _sentinel_state() -> dict:
    """A hostile full state with high-entropy sentinels across EVERY hidden surface (§6.5)."""
    s = _full_state(threshold=0)
    secret = s["state"]["entities"][2]["fields"]
    secret["block_threshold"]["value"] = "SENTINELthreshold7Q2"   # the threshold VALUE
    secret["subject_route"]["value"] = "SENTINELsubjroute8K4"     # the hidden subject route
    # the realistic ROUTE_SECRET id prefix "route_secret:" trips secret_scan's generic keyword rule on this
    # deliberate fake sentinel; pragma it (the scanner's documented test-fixture escape hatch).
    s["state"]["entities"][2]["id"] = "route_secret:SENTINELhidid9Z1"  # pragma: allowlist secret
    s["state"]["scenario_label"] = "SENTINELlabel3X8"             # a scenario label
    # a SECOND hidden threshold (the 'RED matters' both-blockable game adds route_secret:r2) -- its value
    # must be just as unreachable. Same ROUTE_SECRET type, so the type-filter must drop it too.
    s["state"]["entities"].append({"id": "route_secret:r2", "type": "ROUTE_SECRET", "fields": {
        "subject_route": {"value": "r2", "unit": "id"},
        "block_threshold": {"value": "SENTINELr2thresh5N3", "unit": "d100"}}})
    return s


def test_no_hidden_sentinel_reaches_the_request() -> None:
    view = project_turn_record("BLUE", {"turn": 0, "resulting_state": _sentinel_state(), "event_batch": []})
    sentinels = ["SENTINELthreshold7Q2", "SENTINELsubjroute8K4", "SENTINELhidid9Z1", "SENTINELlabel3X8",
                 "SENTINELr2thresh5N3"]
    for pv in pt.APPROVED_PROMPT_VERSIONS:                        # no hidden value reaches ANY approved template
        assert pt.request_contains_any(pv, view, sentinels) == []


def test_sentinel_scan_has_teeth_on_a_leaky_template() -> None:
    # A deliberately LEAKY template (a secret sentinel baked into a FIXED part). It is a valid registered
    # template that self-binds green -- which is exactly why the binding alone is insufficient and the
    # sentinel scan is a load-bearing leg (§2.5). The scan must CATCH the leak on EVERY fixed surface the
    # spec covers: system prose, the tool schema, AND the user-instruction prefix (§6.5).
    leaked = "SENTINELthreshold7Q2"
    import copy as _copy
    leaky_tool = _copy.deepcopy(pt._SUBMIT_COMMAND_TOOL)
    leaky_tool["description"] = leaky_tool["description"] + f" (threshold {leaked})"
    surfaces = {
        "system": pt._spec(system=pt._SYSTEM_PROSE + f" The block threshold is {leaked}.", tool=pt._SUBMIT_COMMAND_TOOL),
        "tools": pt._spec(system=pt._SYSTEM_PROSE, tool=leaky_tool),
        "user_prefix": pt._spec(system=pt._SYSTEM_PROSE, tool=pt._SUBMIT_COMMAND_TOOL,
                                user_prefix=pt.FIXED_INSTRUCTION_PREFIX + f"(threshold {leaked})\n"),
    }
    view = _fog_view(threshold=0)
    for surface, leaky_spec in surfaces.items():
        leaky_pv = pt.prompt_version_of(leaky_spec)
        pt.PROMPT_TEMPLATES[leaky_pv] = leaky_spec
        try:
            assert pt.request_contains_any(leaky_pv, view, [leaked]) == [leaked], f"leak via {surface} missed"
            # ...and it self-binds: re-rendering is byte-identical (proving "leaky template binds green").
            assert pt.canonical_request_bytes(leaky_pv, view) == pt.canonical_request_bytes(leaky_pv, view)
        finally:
            del pt.PROMPT_TEMPLATES[leaky_pv]   # never leave a leaky template registered

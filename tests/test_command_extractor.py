"""Behavior tests for the strict command extractor (core/command_extractor.py).

The extractor decides WELL-FORMEDNESS ONLY: a valid recorded response yields exactly
``{action_type, params}`` (never identity), and each malformed response is rejected for exactly one
pinned reason. Legality (quantity range, known route/action) is NOT the extractor's job — a well-formed
but illegal action extracts fine and is later a ``validate_all`` rejection.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from command_extractor import (
    REJECT_CODES,
    extract_command,
    project_semantic,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "agent_bytes"

# Each invalid fixture fails for EXACTLY this one reject code (single-fault).
INVALID_CASES = {
    "not_json.json": "malformed-bytes",
    "no_content_list.json": "malformed-bytes",
    "no_command.json": "no-command",
    "ambiguous_two_commands.json": "ambiguous-command",
    "input_not_mapping.json": "semantic-field-invalid",
    "extra_key_identity.json": "semantic-field-invalid",
    "missing_params.json": "semantic-field-invalid",
    "params_not_mapping.json": "semantic-field-invalid",
    "action_not_string.json": "semantic-field-invalid",
    "non_canon_float.json": "non-canon-command",
    "unknown_action.json": "unknown-action",            # NUKE — no closed schema (WP-A1b amend 1)
    "prose_in_params.json": "params-schema-mismatch",   # a rationale key smuggled into params
    "quantity_not_int.json": "params-schema-mismatch",  # wrong scalar type
    "prose_in_route.json": "params-schema-mismatch",    # free-form prose in the route enum field
}


def _bytes(rel: str) -> bytes:
    return (FIX / rel).read_bytes()


import json  # noqa: E402


def _resp(action: str, params: dict) -> bytes:
    return json.dumps({"role": "assistant", "content": [
        {"type": "tool_use", "name": "submit_command",
         "input": {"action_type": action, "params": params}}]}).encode()


@pytest.mark.parametrize("name", ["dispatch_r1.json", "block_r1.json"])
def test_valid_fixtures_extract_to_semantic_pair_only(name: str) -> None:
    r = extract_command(_bytes(f"valid/{name}"))
    assert r.ok, r.reject_detail
    assert r.reject_code is None
    assert set(r.command.keys()) == {"action_type", "params"}  # never command_id/turn/actor_id
    assert isinstance(r.command["action_type"], str)
    assert isinstance(r.command["params"], dict)


def test_extraction_is_not_value_RANGE_legality() -> None:
    # the [1,30] quantity RANGE stays validate_all's job: an out-of-range quantity still EXTRACTS cleanly
    # (an int is shape-valid). But an unknown route (not in the enum) is a SHAPE reject here (prose closure).
    assert extract_command(_resp("DISPATCH_SUPPLY", {"quantity": 999, "route": "r1"})).ok
    r = extract_command(_resp("DISPATCH_SUPPLY", {"quantity": 30, "route": "r9"}))
    assert not r.ok and r.reject_code == "params-schema-mismatch"


@pytest.mark.parametrize("name,code", list(INVALID_CASES.items()), ids=list(INVALID_CASES))
def test_invalid_fixtures_reject_with_one_code(name: str, code: str) -> None:
    r = extract_command(_bytes(f"invalid/{name}"))
    assert not r.ok
    assert r.command is None
    assert r.reject_code == code, f"{name}: expected {code}, got {r.reject_code} ({r.reject_detail})"


def test_reject_codes_are_pinned_and_each_is_exercised() -> None:
    assert set(INVALID_CASES.values()) == set(REJECT_CODES)


def test_never_take_first_on_ambiguity() -> None:
    # two well-formed commands must REJECT, not silently pick one
    r = extract_command(_bytes("invalid/ambiguous_two_commands.json"))
    assert not r.ok and r.reject_code == "ambiguous-command"


def test_project_semantic_is_the_two_authored_fields() -> None:
    cmd = {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 3, "route": "r1"},
           "command_id": "x", "turn": 0, "actor_id": "BLUE"}
    assert project_semantic(cmd) == {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 3, "route": "r1"}}

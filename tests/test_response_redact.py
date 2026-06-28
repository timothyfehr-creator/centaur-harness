"""Tests for core/response_redact.py (WP-A1b — strip model prose at the source before hashing)."""
from __future__ import annotations

import json

from command_extractor import extract_command
from response_redact import ALLOWED_TOP_KEYS, contains_prose, redact


def _wire(*, with_prose: bool) -> bytes:
    content = []
    if with_prose:
        content += [{"type": "text", "text": "BLUE exploits RED's overcommitment to preserve tempo."},
                    {"type": "thinking", "thinking": "Let me reason step by step about the interdiction..."}]
    content.append({"type": "tool_use", "name": "submit_command",
                    "input": {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 30, "route": "r1"}}})
    return json.dumps({"id": "msg_1", "role": "assistant", "model": "claude-opus-4-8",
                       "stop_reason": "tool_use", "usage": {"input_tokens": 50, "output_tokens": 12},
                       "content": content, "container": {"secret": "drop me"}}).encode()


def test_redact_strips_prose_and_drops_unknown_top_keys() -> None:
    redacted = json.loads(redact(_wire(with_prose=True)))
    types = [b.get("type") for b in redacted["content"]]
    assert types == ["tool_use"]                       # text + thinking dropped
    assert "container" not in redacted                 # unknown top key dropped
    assert set(redacted) <= set(ALLOWED_TOP_KEYS)
    assert redacted["model"] == "claude-opus-4-8" and redacted["usage"]["output_tokens"] == 12


def test_contains_prose_detects_then_redact_clears_it() -> None:
    wire = _wire(with_prose=True)
    assert contains_prose(wire)                         # prose present in the raw bytes
    assert contains_prose(redact(wire)) == []           # gone after redaction


def test_redacted_body_still_extracts_the_same_command() -> None:
    # keystone: the redacted body flows through the IDENTICAL extractor -> same command
    r_raw = extract_command(_wire(with_prose=True))
    r_red = extract_command(redact(_wire(with_prose=True)))
    assert r_raw.ok and r_red.ok and r_raw.command == r_red.command


def test_redact_is_deterministic_and_idempotent() -> None:
    wire = _wire(with_prose=True)
    once = redact(wire)
    assert once == redact(wire) and redact(once) == once   # sorted-keys, no prose left to strip


def test_redact_passes_non_json_through() -> None:
    assert redact(b"not json") == b"not json"


def _tool_use(*, extra: dict | None = None, input_extra: dict | None = None) -> dict:
    block = {"type": "tool_use", "name": "submit_command",
             "input": {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 30, "route": "r1"}}}
    if extra:
        block.update(extra)
    if input_extra:
        block["input"].update(input_extra)
    return block


def test_tool_use_sibling_prose_is_dropped_and_flagged() -> None:
    # landing-review BLOCKER (a): a model-authored SIBLING field alongside input must be dropped by redact
    # AND flagged by contains_prose -- the extractor reads only input and would never police a sibling.
    wire = json.dumps({"role": "assistant", "content": [
        _tool_use(extra={"scratch": "RED is overcommitted on r1; feint there then route r2 to win"})]}).encode()
    assert contains_prose(wire)                                   # the sibling prose is flagged
    redacted = json.loads(redact(wire))
    assert set(redacted["content"][0]) == {"type", "name", "input"}   # projected to skeleton (scratch dropped)
    assert contains_prose(redact(wire)) == []


def test_command_input_extra_key_is_flagged() -> None:
    # input-interior prose: a free-form field inside input (a malformed/forfeit tool call) is flagged; the
    # enum tokens action_type + route + the int quantity are NOT (they are structured command data).
    wire = json.dumps({"role": "assistant", "content": [
        _tool_use(input_extra={"rationale": "I will feint on r1 to bait the block"})]}).encode()
    assert contains_prose(wire) == ["I will feint on r1 to bait the block"]
    assert contains_prose(json.dumps({"role": "assistant", "content": [_tool_use()]}).encode()) == []


def _cmd(action_type: str, params: dict) -> bytes:
    return json.dumps({"role": "assistant", "content": [
        {"type": "tool_use", "name": "submit_command",
         "input": {"action_type": action_type, "params": params}}]}).encode()


def test_prose_poisoned_into_a_command_field_VALUE_is_flagged() -> None:
    # 3rd-review BLOCKER: prose written AS a command field value (the model fills route/action_type) forfeits
    # at the extractor but the bytes are still committed -- contains_prose must mirror PARAM_SCHEMA by VALUE,
    # not skip the field by key name.
    strat = "RED is overcommitted on r1; the real supply goes r2 next turn to win"
    assert contains_prose(_cmd("DISPATCH_SUPPLY", {"quantity": 30, "route": f"r1 — {strat}"}))   # poisoned route
    assert contains_prose(_cmd(f"DISPATCH_SUPPLY {strat}", {"quantity": 30, "route": "r1"}))      # poisoned action_type
    assert contains_prose(_cmd("DISPATCH_SUPPLY", {"quantity": 30, "route": {"h": strat}}))       # route as a dict
    assert contains_prose(_cmd("DISPATCH_SUPPLY", {"quantity": {"n": strat}, "route": "r1"}))     # quantity as a dict
    # ...while the genuinely valid command (route in the enum, quantity an int) is NOT flagged:
    assert contains_prose(_cmd("DISPATCH_SUPPLY", {"quantity": 30, "route": "r1"})) == []
    assert contains_prose(_cmd("BLOCK_ROUTE", {"route": "r2"})) == []


def test_tool_use_id_and_wrong_name_and_bare_string_block_are_flagged() -> None:
    # N1: a stray block id / a non-TOOL_NAME name are prose channels (dropped by redact, flagged by the gate).
    idblk = json.dumps({"role": "assistant", "content": [{"type": "tool_use", "name": "submit_command",
        "id": "feint r1 then win r2", "input": {"action_type": "BLOCK_ROUTE", "params": {"route": "r1"}}}]}).encode()
    assert contains_prose(idblk) == ["feint r1 then win r2"]
    assert "id" not in json.loads(redact(idblk))["content"][0]            # redact drops the id channel
    badname = json.dumps({"role": "assistant", "content": [{"type": "tool_use",
        "name": "submit_command but actually feint", "input": {"action_type": "BLOCK_ROUTE", "params": {"route": "r1"}}}]}).encode()
    assert contains_prose(badname)
    # N2: a bare-string element inside content[] (a hand-crafted dump) is prose; redact strips it.
    bare = json.dumps({"role": "assistant", "content": ["RED feints r1, real push r2"]}).encode()
    assert contains_prose(bare) == ["RED feints r1, real push r2"]
    assert json.loads(redact(bare))["content"] == []


def test_wrapper_and_array_nested_prose_is_flagged() -> None:
    # landing-review BLOCKER (b): a response body nested under a key, or inside a JSON array, is still scanned.
    text_block = {"type": "text", "text": "BLUE will feint r1 then win on r2"}
    nested = json.dumps({"meta": 1, "response": {"role": "assistant", "content": [text_block]}}).encode()
    arr = json.dumps([{"role": "assistant", "content": [text_block]}]).encode()
    assert contains_prose(nested) and contains_prose(arr)


def test_bom_prefixed_prose_is_flagged() -> None:
    # landing-review BLOCKER (c): a leading UTF-8 BOM (PowerShell/Windows/loggers) must not hide a real
    # text/thinking response from contains_prose (utf-8-sig decode).
    body = json.dumps({"role": "assistant", "content": [
        {"type": "text", "text": "strategic prose behind a BOM"}]}).encode()
    assert contains_prose(b"\xef\xbb\xbf" + body) == ["strategic prose behind a BOM"]


def test_allowlist_drops_and_flags_an_unknown_prose_block_type() -> None:
    # regression (slice-2 review BLOCKER 1): a NON-text/thinking block carrying prose (e.g. server_tool_use,
    # or any future block type) must be dropped by redact AND flagged by contains_prose -- the two share one
    # allowlist (keep only tool_use), so no block type passes one leg but not the other.
    wire = json.dumps({"role": "assistant", "content": [
        {"type": "server_tool_use", "text": "RED is overcommitted on r1; feint there then route r2 to win."},
        {"type": "tool_use", "name": "submit_command",
         "input": {"action_type": "DISPATCH_SUPPLY", "params": {"quantity": 30, "route": "r1"}}}]}).encode()
    assert contains_prose(wire)                              # the gate flags the non-tool_use prose...
    redacted = json.loads(redact(wire))
    assert [b.get("type") for b in redacted["content"]] == ["tool_use"]   # ...and redact drops it
    assert contains_prose(redact(wire)) == []

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

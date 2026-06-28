#!/usr/bin/env python3
"""Versioned prompt-template registry (WP-A1b §2.2) — the request-envelope render, PURE + offline.

``render_request_envelope(prompt_version, fog_view) -> dict`` returns the Anthropic Messages request
BODY (model, max_tokens, system, tools, tool_choice, messages). It is PURE and DETERMINISTIC: no clock,
no nonce, no request-id, no network, no float. Shared by the (deferred) live producer AND the binding
gate, so the gate can RE-RENDER the captured request and bind it by sha256 (§2.3-2.4).

The honesty leg this module carries (§2.2 leg 3 / §2.5 leg 3 — "a leaky template binds green"):
the FIXED part of the envelope (system prose, the ``submit_command`` schema, the pins) is a pure
function of ``prompt_version`` ALONE — it has NO access to secret game state (``block_threshold``,
``master_seed``). Only the user content varies, and only with the PUBLIC fog projection
(``canonical_bytes(fog_view)``). Two structural checks prove this rather than asserting it:
  - the **differential-purity invariant** (``fixed_part``): vary the secret(s) -> the fixed bytes are
    UNCHANGED (tested in tests/test_prompt_templates.py);
  - the **secret-sentinel scan** (``request_contains_any``): no hidden-surface value appears anywhere
    in ``canonical_request_bytes`` (amendment 5).

``prompt_version`` is a CONTENT HASH of the template spec (Fork B) — any change to the system prose,
the tool schema, the pins, or the render logic (``RENDER_VERSION``) moves the version, so a registered
version names exactly one byte-pinned template. The binding gate additionally requires the version to be
on the human-curated ``APPROVED_PROMPT_VERSIONS`` allowlist (registered != audited, §2.2 leg 1).

A1b shape (§1.3 + amendments): forced single ``submit_command`` tool; NO ``thinking`` field (amend 8 —
omitted for Opus 4.8); NO ``temperature``/``seed``/``top_p`` (un-spellable; sampling is provider-default).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canon import canonical_bytes, canonical_digest  # noqa: E402

# Bumps when render_user's logic changes (so a render change moves prompt_version even with identical pins).
RENDER_VERSION = 1

# Pins (§1.3, amended). model/max_tokens/anthropic_version are part of the version digest; anthropic_version
# rides as a header (not a body param) so it is absent from the rendered body, present in the version hash.
_MODEL = "claude-opus-4-8"
_MAX_TOKENS = 1024
_ANTHROPIC_VERSION = "2023-06-01"

# The fog view's public route ids (mirrors core/command_extractor.ROUTE_IDS); the tool schema is closed over
# them so the model cannot author a free-form route string (amendment 1 — no prose channel in params).
_ROUTE_IDS = ["r1", "r2"]

# The fixed, game-RULE (public) system prose. It describes the PUBLIC rules only; it never names a threshold,
# a seed, or any per-instance secret. Byte-pinned: editing it moves prompt_version + must re-enter the allowlist.
_SYSTEM_PROSE = (
    "You are a commander in a turn-based contested-logistics exercise. You command the side named by the "
    "`viewer` field in the state JSON below. There are two roles, each with exactly ONE legal action:\n"
    "- BLUE (the logistics force) may ONLY issue DISPATCH_SUPPLY, moving an integer quantity between 1 and "
    "30 units along route r1 or r2.\n"
    "- RED (the interdiction force) may ONLY issue BLOCK_ROUTE, choosing route r1 or r2 to block.\n"
    "Supply moves from origin to the front along routes r1 and r2; an adversary may attempt to block a route. "
    "You see only the current public state; hidden adversary parameters are not disclosed. Issue exactly one "
    "order that is LEGAL FOR YOUR ROLE by calling the submit_command tool: an order with the wrong action for "
    "your role, or a quantity outside 1-30, forfeits your turn. Do not narrate; the tool call is the entire "
    "output the exercise records."
)

# The closed submit_command tool schema (mirrors the strict extractor's PARAM_SCHEMA: closed per-action
# params, route as an enum, quantity an integer — no free-form/rationale field can be expressed).
_SUBMIT_COMMAND_TOOL = {
    "name": "submit_command",
    "description": "Submit this turn's single order.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action_type", "params"],
        "properties": {
            "action_type": {"type": "string", "enum": ["DISPATCH_SUPPLY", "BLOCK_ROUTE"]},
            "params": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "quantity": {"type": "integer", "minimum": 0},
                    "route": {"type": "string", "enum": list(_ROUTE_IDS)},
                },
            },
        },
    },
}

_TOOL_CHOICE = {"type": "tool", "name": "submit_command", "disable_parallel_tool_use": True}

# The fixed user-content prefix; the only non-fixed user bytes are canonical_bytes(fog_view) appended after it.
FIXED_INSTRUCTION_PREFIX = (
    "Current fog-of-war view of the exercise (PUBLIC information only) as canonical JSON follows. "
    "Decide your single order and submit it via the submit_command tool.\n"
)


def _spec(*, system: str, tool: dict, user_prefix: str = FIXED_INSTRUCTION_PREFIX) -> dict:
    """One template spec. ``system``/``tool``/``user_prefix`` are the audited, byte-pinned, secret-free fixed
    parts; ``user_prefix`` is the fixed user-instruction prefix the fog view is appended to (§2.2)."""
    return {
        "system": system,
        "tool": tool,
        "user_prefix": user_prefix,
        "model": _MODEL,
        "max_tokens": _MAX_TOKENS,
        "anthropic_version": _ANTHROPIC_VERSION,
        "tool_choice": _TOOL_CHOICE,
        "render_version": RENDER_VERSION,
    }


def prompt_version_of(spec: dict) -> str:
    """The content-hash version id (Fork B): any change to a pinned field or the render logic moves it.
    Covers the ENTIRE fixed request including the user-instruction PREFIX (amendment 4 — the §2 gap the
    external reviewer flagged: a prefix edit must move the version + re-enter the audited allowlist, not ride
    an approved version by RENDER_VERSION convention alone)."""
    payload = {
        "system": spec["system"], "tool": spec["tool"], "user_prefix": spec["user_prefix"],
        "model": spec["model"], "anthropic_version": spec["anthropic_version"],
        "max_tokens": spec["max_tokens"], "tool_choice": spec["tool_choice"],
        "render_version": spec["render_version"],
    }
    return "ptmpl-" + canonical_digest(payload)["value"][:16]


# The single A1b template + its derived, content-pinned version id.
_A1B_SPEC = _spec(system=_SYSTEM_PROSE, tool=_SUBMIT_COMMAND_TOOL)
A1B_PROMPT_VERSION = prompt_version_of(_A1B_SPEC)

# The registry: prompt_version -> spec. APPROVED is the human-curated allowlist the binding gate requires
# (a merely-registered version is NOT enough — §2.2 leg 1). Both are this single audited template for A1b.
PROMPT_TEMPLATES: dict[str, dict] = {A1B_PROMPT_VERSION: _A1B_SPEC}
APPROVED_PROMPT_VERSIONS: tuple[str, ...] = (A1B_PROMPT_VERSION,)


def _render_user(user_prefix: str, fog_view: dict) -> str:
    """The user content = the template's fixed prefix + the canonical bytes of the PUBLIC fog view (the only
    variable part). The prefix is part of the content-pinned spec, so a prefix edit moves prompt_version."""
    return user_prefix + canonical_bytes(fog_view).decode("utf-8")


def render_request_envelope(prompt_version: str, fog_view: dict) -> dict:
    """Render the Messages request BODY for ``prompt_version`` applied to ``fog_view``. Pure/deterministic.

    Raises ``KeyError`` for an unregistered version — the CALLER (the binding gate) fails closed (exit 2)
    on an unknown/unapproved version; this module does not decide policy, it just refuses to invent a body.
    """
    spec = PROMPT_TEMPLATES[prompt_version]
    return {
        "model": spec["model"],
        "max_tokens": spec["max_tokens"],
        "system": spec["system"],
        "tools": [spec["tool"]],
        "tool_choice": spec["tool_choice"],
        "messages": [{"role": "user", "content": _render_user(spec["user_prefix"], fog_view)}],
    }


def canonical_request_bytes(prompt_version: str, fog_view: dict) -> bytes:
    """The canon-v1 bytes the live producer commits + the binding gate re-hashes (§1.4 step 4 / §2.3)."""
    return canonical_bytes(render_request_envelope(prompt_version, fog_view))


def fixed_part(envelope: dict) -> dict:
    """The secret-INDEPENDENT part of a rendered envelope (everything except the per-view ``messages``).
    The differential-purity invariant asserts canonical_bytes(fixed_part(env)) is constant across secrets."""
    return {k: v for k, v in envelope.items() if k != "messages"}


def request_contains_any(prompt_version: str, fog_view: dict, needles: list[str]) -> list[str]:
    """Return any ``needles`` (hidden-surface sentinels) that appear in the rendered request bytes (amend 5).
    A non-empty result means a secret reached the wire — the request is NOT secret-pure."""
    raw = canonical_request_bytes(prompt_version, fog_view)
    return [n for n in needles if n.encode("utf-8") in raw]

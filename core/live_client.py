"""The ONLY network-touching module (WP-A1b §1.2) — @live, OUT of the green gate.

It is the sole importer of ``anthropic`` (allowlisted by path in validate_no_network_imports) and is NEVER
imported by a test (the determinism guard asserts ``anthropic`` is absent from ``sys.modules`` during the
gate run). It takes a fully-rendered request BODY, POSTs it NON-streaming with ``max_retries=0`` + an
explicit timeout (so the captured artifact's spend == the billed spend; a silent retry would double-bill and
desync the capture), NO fallbacks, and returns the EXACT raw HTTP response bytes (``raw.content`` — Fork D,
NOT a pydantic re-serialization) plus the parsed served-model / usage / stop-reason / request-id.

The api-key is read from ``ANTHROPIC_API_KEY`` by the SDK and rides as the ``x-api-key`` HEADER — never in
the request body, never in any returned or committed artifact. This module renders nothing and decides no
policy (the caller holds the spend guard + drift handling); it just performs the one POST honestly.
"""
from __future__ import annotations

from dataclasses import dataclass

import anthropic

# count_tokens accepts only these body keys (not max_tokens / not a streaming flag).
_COUNT_TOKENS_KEYS = ("messages", "model", "system", "tools", "tool_choice")


@dataclass(frozen=True)
class LiveResult:
    """One captured live call. ``wire_response_bytes`` is the exact HTTP body to redact + hash."""
    wire_response_bytes: bytes
    served_model: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    provider_request_id: str


def _client(timeout: float) -> "anthropic.Anthropic":
    # max_retries=0: artifact spend == billed spend (no hidden retry). The key comes from the env (header).
    return anthropic.Anthropic(max_retries=0, timeout=timeout)


def count_input_tokens(body: dict, *, timeout: float = 30.0) -> int:
    """The provider's input-token count for this request (feeds the proactive spend guard). A network+auth
    call (count_tokens itself bills nothing but needs the key) — confined to the human-run capture, never a test."""
    kwargs = {k: body[k] for k in _COUNT_TOKENS_KEYS if k in body and body[k] is not None}
    ct = _client(timeout).messages.count_tokens(**kwargs)
    return int(ct.input_tokens)


def call(body: dict, *, timeout: float = 60.0) -> LiveResult:
    """One non-streaming Messages call. Returns the raw wire bytes + parsed metadata. Raises on an HTTP/transport
    error (an unusable capture — the caller records it EXCLUDED, never a committed binding step)."""
    raw = _client(timeout).messages.with_raw_response.create(**body)   # LegacyAPIResponse
    msg = raw.parse()                                                  # typed Message (model/usage/stop_reason)
    return LiveResult(
        wire_response_bytes=raw.content,                              # exact HTTP response body bytes (Fork D)
        served_model=msg.model,
        stop_reason=msg.stop_reason,
        input_tokens=int(msg.usage.input_tokens),
        output_tokens=int(msg.usage.output_tokens),
        provider_request_id=raw.request_id or "",
    )

"""Response redaction (WP-A1b amendment 1/2) — strip model prose at the SOURCE, before hashing.

The external review's CRUX finding: committing the raw provider response body to git publishes the model's
strategic ``text``/``thinking`` prose verbatim — a decision-facing transcript under green gates, the exact
WP-A0 disqualifier. The fix is to REDACT the prose at capture, BEFORE the bytes are hashed and committed,
and keep only what Centaur reads: the ``submit_command`` ``tool_use`` block(s) + an allowlisted set of
top-level keys. The full wire bytes (which DO contain prose) are kept run-local + gitignored for the
operator's one authenticity glance (the live lane); the COMMITTED bytes are prose-free.

This is keystone-compatible: ``extract_command`` already reads only the ``tool_use`` block's ``input``, so
the redacted body flows through the IDENTICAL pipeline (the deliverable digest is unchanged). Byte-identity
of replay holds; only the word "raw" becomes "redacted-at-source".

DEFENSE-IN-DEPTH (per the slice-2 adversarial review): both legs are ALLOWLISTS, not denylists. ``redact``
keeps ONLY ``tool_use`` content blocks (so a future/other prose-bearing block type — ``thinking`` had to be
enumerated after the fact, and ``server_tool_use``/web-search-result blocks also carry free text — cannot
survive by virtue of not being on a hand-maintained drop-list). ``contains_prose`` symmetrically flags ANY
non-``tool_use`` content block that carries a non-empty string, so the gate and the redactor share the same
allowlist and there is no block type that passes one but not the other.
"""
from __future__ import annotations

import json

# Top-level response keys Centaur reads (model/usage/stop_reason for LIVE provenance + drift/accounting;
# id for the request-id cross-check; role+content for extraction). Everything else is dropped before commit.
ALLOWED_TOP_KEYS = ("role", "content", "model", "stop_reason", "usage", "id")
# The ONLY content block type committed. Everything else is non-allowlisted -> dropped by redact + flagged by
# contains_prose. An allowlist (not a denylist of prose types) so a new prose-bearing block type cannot leak.
KEPT_BLOCK_TYPES = ("tool_use",)


def _strings_in(value: object) -> list[str]:
    """Every non-empty string anywhere in a content block, EXCEPT the block's ``type`` tag (which is a short
    machine label like "text"/"tool_use", not prose). Recursive so prose nested in a sub-field is still seen."""
    out: list[str] = []
    if isinstance(value, str):
        if value:
            out.append(value)
    elif isinstance(value, list):
        for item in value:
            out.extend(_strings_in(item))
    elif isinstance(value, dict):
        for key, val in value.items():
            if key == "type":
                continue
            out.extend(_strings_in(val))
    return out


def _prose_strings(body: object) -> list[str]:
    """Every prose string in a (parsed) response body: any string carried by a NON-tool_use content block.
    (Prose inside a kept ``tool_use`` block's ``input`` is the strict extractor's closed-schema job, not this
    gate's — a free-form params field fails ``params-schema-mismatch`` before commit.)"""
    out: list[str] = []
    if isinstance(body, dict) and isinstance(body.get("content"), list):
        for block in body["content"]:
            if isinstance(block, dict) and block.get("type") not in KEPT_BLOCK_TYPES:
                out.extend(_strings_in(block))
    return out


def redact(wire_bytes: bytes) -> bytes:
    """Return the prose-free committed body: keep ONLY ``tool_use`` content blocks (allowlist) and the
    allowlisted top-level keys; re-serialize deterministically (sorted keys). The kept tool_use block(s) flow
    through the identical extractor. Returns the input unchanged if it is not a JSON object."""
    try:
        body = json.loads(wire_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return wire_bytes
    if not isinstance(body, dict):
        return wire_bytes
    kept = {k: v for k, v in body.items() if k in ALLOWED_TOP_KEYS}
    if isinstance(body.get("content"), list):
        kept["content"] = [b for b in body["content"]
                           if isinstance(b, dict) and b.get("type") in KEPT_BLOCK_TYPES]
    return json.dumps(kept, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def contains_prose(raw: bytes) -> list[str]:
    """The prose strings present in a committed artifact, if any (for the global no-prose gate). Empty list
    means prose-free. Non-JSON / non-response bytes have no response content blocks -> empty."""
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    return _prose_strings(body)

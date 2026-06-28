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
"""
from __future__ import annotations

import json

# Top-level response keys Centaur reads (model/usage/stop_reason for LIVE provenance + drift/accounting;
# id for the request-id cross-check; role+content for extraction). Everything else is dropped before commit.
ALLOWED_TOP_KEYS = ("role", "content", "model", "stop_reason", "usage", "id")
# Content block types that carry the model's free prose. Dropped entirely from the committed body.
PROSE_BLOCK_TYPES = ("text", "thinking", "redacted_thinking")


def _prose_strings(body: object) -> list[str]:
    """Every non-empty prose-block string in a (parsed) response body."""
    out: list[str] = []
    if isinstance(body, dict) and isinstance(body.get("content"), list):
        for block in body["content"]:
            if isinstance(block, dict) and block.get("type") in PROSE_BLOCK_TYPES:
                for key in ("text", "thinking", "data"):
                    val = block.get(key)
                    if isinstance(val, str) and val:
                        out.append(val)
    return out


def redact(wire_bytes: bytes) -> bytes:
    """Return the prose-free committed body: drop every text/thinking/redacted_thinking content block and
    every non-allowlisted top-level key; re-serialize deterministically (sorted keys). The kept tool_use
    block(s) flow through the identical extractor. Returns the input unchanged if it is not a JSON object."""
    try:
        body = json.loads(wire_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return wire_bytes
    if not isinstance(body, dict):
        return wire_bytes
    kept = {k: v for k, v in body.items() if k in ALLOWED_TOP_KEYS}
    if isinstance(body.get("content"), list):
        kept["content"] = [b for b in body["content"]
                           if not (isinstance(b, dict) and b.get("type") in PROSE_BLOCK_TYPES)]
    return json.dumps(kept, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def contains_prose(raw: bytes) -> list[str]:
    """The prose strings present in a committed artifact, if any (for the global no-prose gate). Empty list
    means prose-free. Non-JSON / non-response bytes have no response prose blocks -> empty."""
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    return _prose_strings(body)

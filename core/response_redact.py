"""Response redaction (WP-A1b amendment 1/2) — strip model prose at the SOURCE, before hashing.

The external review's CRUX finding: committing the raw provider response body to git publishes the model's
strategic ``text``/``thinking`` prose verbatim — a decision-facing transcript under green gates, the exact
WP-A0 disqualifier. The fix is to REDACT the prose at capture, BEFORE the bytes are hashed and committed,
and keep only what Centaur reads: the ``submit_command`` ``tool_use`` block(s) PROJECTED TO THEIR SKELETON
``{type,id,name,input}`` + an allowlisted set of top-level keys. The full wire bytes (which DO contain prose)
are kept run-local + gitignored for the operator's one authenticity glance (the live lane); the COMMITTED
bytes are prose-free.

This is keystone-compatible: ``extract_command`` already reads only the ``tool_use`` block's ``input``, so
the redacted body flows through the IDENTICAL pipeline (the deliverable digest is unchanged). Byte-identity
of replay holds; only the word "raw" becomes "redacted-at-source".

DEFENSE-IN-DEPTH (per two adversarial reviews). Both legs are ALLOWLISTS, not denylists, and the gate's
detection matches the redactor's projection so there is no shape that passes one but not the other:
  - ``redact`` keeps ONLY ``tool_use`` content blocks AND PROJECTS each to ``{type,id,name,input}`` — so a
    model-authored SIBLING field (e.g. ``"scratch":"<strategy>"`` alongside ``input``) cannot ride along
    (the extractor reads only ``input`` and would never see it).
  - ``contains_prose`` flags ANY string in a NON-tool_use block, ANY sibling key of a tool_use block, and ANY
    string in a tool_use ``input`` that is not a command enum token (``action_type`` / ``params.route``;
    ``quantity`` is an int) — mirroring command_extractor's closed PARAM_SCHEMA. It recurses to find a
    response body nested under a key or inside an ARRAY (a wrapped "debug dump"), and decodes ``utf-8-sig``
    so a leading BOM cannot hide a genuine prose response.
"""
from __future__ import annotations

import json

# Top-level response keys Centaur reads (model/usage/stop_reason for LIVE provenance + drift/accounting;
# id for the request-id cross-check; role+content for extraction). Everything else is dropped before commit.
ALLOWED_TOP_KEYS = ("role", "content", "model", "stop_reason", "usage", "id")
# The ONLY content block type committed, and the ONLY keys kept on it (its structural skeleton). An allowlist
# (not a denylist) so a new prose-bearing block type / sibling field cannot leak.
KEPT_BLOCK_TYPES = ("tool_use",)
TOOL_USE_SKELETON_KEYS = ("type", "id", "name", "input")
# The only STRING leaves a committed command tool_use ``input`` may carry (mirrors command_extractor
# PARAM_SCHEMA: action_type + the route enum; quantity is an int). Any other input string is prose.
_COMMAND_STRING_INPUT_KEYS = ("action_type",)
_COMMAND_STRING_PARAM_KEYS = ("route",)
_COMMAND_INT_PARAM_KEYS = ("quantity",)


def _all_strings(value: object) -> list[str]:
    """Every non-empty string anywhere in ``value`` (recursive)."""
    out: list[str] = []
    if isinstance(value, str):
        if value:
            out.append(value)
    elif isinstance(value, list):
        for item in value:
            out.extend(_all_strings(item))
    elif isinstance(value, dict):
        for val in value.values():
            out.extend(_all_strings(val))
    return out


def _command_input_prose(inp: object) -> list[str]:
    """Strings in a tool_use ``input`` that are NOT command enum tokens. A valid command input is
    ``{action_type: enum, params: {quantity: int, route: enum}}``; everything else (a free-string input, a
    ``rationale`` field, an extra key, a non-int quantity) is prose."""
    if not isinstance(inp, dict):
        return _all_strings(inp)               # an input that is not an object (e.g. a bare string) is prose
    out: list[str] = []
    for key, val in inp.items():
        if key in _COMMAND_STRING_INPUT_KEYS:
            continue                            # the action_type enum token is not prose
        if key == "params" and isinstance(val, dict):
            for pkey, pval in val.items():
                if pkey in _COMMAND_STRING_PARAM_KEYS:
                    continue                    # the route enum token is not prose
                if pkey in _COMMAND_INT_PARAM_KEYS and not isinstance(pval, str):
                    continue                    # quantity is an int, not prose
                out.extend(_all_strings(pval))
            continue
        out.extend(_all_strings(val))           # any other input key (rationale/note/...) is prose
    return out


def _tool_use_prose(block: dict) -> list[str]:
    """Prose carried by a tool_use block: any sibling key (outside the skeleton) + any non-token input string."""
    out: list[str] = []
    for key, val in block.items():
        if key in ("type", "id", "name"):
            continue                            # structural scalars, not prose
        if key == "input":
            out.extend(_command_input_prose(val))
        else:
            out.extend(_all_strings(val))       # a sibling key -> prose
    return out


def _content_lists(node: object) -> list[list]:
    """Every value under a ``content`` key that is a list, found ANYWHERE in the JSON tree — so a response
    body nested under a key or inside an array (a wrapped raw dump) is still inspected, not just top level."""
    out: list[list] = []
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "content" and isinstance(val, list):
                out.append(val)
            out.extend(_content_lists(val))
    elif isinstance(node, list):
        for item in node:
            out.extend(_content_lists(item))
    return out


def _prose_strings(body: object) -> list[str]:
    """Every prose string in a (parsed) response body, anywhere in the tree."""
    out: list[str] = []
    for content in _content_lists(body):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in KEPT_BLOCK_TYPES:
                out.extend(_tool_use_prose(block))
            else:                               # any non-tool_use block: every string except the type tag
                out.extend(_all_strings({k: v for k, v in block.items() if k != "type"}))
    return out


def _project_tool_use(block: dict) -> dict:
    """Project a kept tool_use block to its skeleton {type,id,name,input}, dropping any sibling field."""
    return {k: block[k] for k in TOOL_USE_SKELETON_KEYS if k in block}


def redact(wire_bytes: bytes) -> bytes:
    """Return the prose-free committed body: keep ONLY ``tool_use`` content blocks, each PROJECTED to its
    {type,id,name,input} skeleton (siblings dropped), plus the allowlisted top-level keys; re-serialize
    deterministically (sorted keys). The kept tool_use block(s) flow through the identical extractor. Returns
    the input unchanged if it is not a JSON object."""
    try:
        body = json.loads(wire_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return wire_bytes
    if not isinstance(body, dict):
        return wire_bytes
    kept = {k: v for k, v in body.items() if k in ALLOWED_TOP_KEYS}
    if isinstance(body.get("content"), list):
        kept["content"] = [_project_tool_use(b) for b in body["content"]
                           if isinstance(b, dict) and b.get("type") in KEPT_BLOCK_TYPES]
    return json.dumps(kept, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def contains_prose(raw: bytes) -> list[str]:
    """The prose strings present in a committed artifact, if any (for the global no-prose gate). Empty list
    means prose-free. ``utf-8-sig`` tolerates a leading BOM; non-JSON / non-response bytes -> empty."""
    try:
        body = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    return _prose_strings(body)

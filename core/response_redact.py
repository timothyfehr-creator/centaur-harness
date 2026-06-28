"""Response redaction (WP-A1b amendment 1/2) — strip model prose at the SOURCE, before hashing.

The external review's CRUX finding: committing the raw provider response body to git publishes the model's
strategic ``text``/``thinking`` prose verbatim — a decision-facing transcript under green gates, the exact
WP-A0 disqualifier. The fix is to REDACT the prose at capture, BEFORE the bytes are hashed and committed,
and keep only what Centaur reads: the ``submit_command`` ``tool_use`` block(s) PROJECTED TO THE CANONICAL
COMMAND SKELETON ``{type, name, input}`` + an allowlisted set of top-level keys. The full wire bytes (which
DO contain prose) are kept run-local + gitignored for the operator's one authenticity glance (the live
lane); the COMMITTED bytes are prose-free.

This is keystone-compatible: ``extract_command`` already reads only the ``tool_use`` block's ``input``, so
the redacted body flows through the IDENTICAL pipeline (the deliverable digest is unchanged). Byte-identity
of replay holds; only the word "raw" becomes "redacted-at-source".

DEFENSE-IN-DEPTH (folded over three adversarial reviews). The committed-response invariant is TIGHT: a
committed response body may contain ONLY canonical command tool_use blocks — ``{type:"tool_use",
name:<TOOL_NAME>, input:<a valid closed-schema command>}`` — nothing else. ``redact`` enforces it by
projection (siblings, a stray block ``id``, every non-``tool_use`` block dropped before hashing) and
``contains_prose`` enforces the SAME invariant at detection, so no shape passes one leg but not the other:
  - any string in a NON-tool_use content block (text/thinking/server_tool_use/...) — flagged;
  - any tool_use key outside ``{type,name,input}`` (a model-authored ``scratch`` sibling, a prose ``id``) —
    flagged; a ``name`` other than ``TOOL_NAME`` — flagged;
  - any string in ``input`` that is not a valid command field BY VALUE — flagged. This MIRRORS
    ``command_extractor.PARAM_SCHEMA`` by value (not by key name): ``action_type`` must be a known command,
    ``route`` must be in the enum, ``quantity`` must be a real int — so prose hidden AS a poisoned field
    value (``route:"r1 <strategy>"``) is caught, exactly as the extractor would reject it;
  - a bare-string element inside ``content[]`` — flagged;
  - a response body nested under a key or inside a JSON ARRAY (a wrapped raw dump) — found by recursion;
  - a leading UTF-8 BOM — tolerated (``utf-8-sig``), so it cannot hide a genuine prose response.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from command_extractor import PARAM_SCHEMA, TOOL_NAME  # noqa: E402 — the single source of the closed schema

# Top-level response keys Centaur reads (model/usage/stop_reason for LIVE provenance + drift/accounting;
# id for the request-id cross-check; role+content for extraction). Everything else is dropped before commit.
ALLOWED_TOP_KEYS = ("role", "content", "model", "stop_reason", "usage", "id")
# The ONLY content block type committed, and the canonical command skeleton kept on it (a stray block id is
# dropped — the extractor never reads it; keeping it would be an un-scanned prose channel).
KEPT_BLOCK_TYPES = ("tool_use",)
TOOL_USE_SKELETON_KEYS = ("type", "name", "input")


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
    """Strings in a tool_use ``input`` that are not valid command fields BY VALUE — mirroring
    command_extractor.PARAM_SCHEMA, so prose hidden as a poisoned enum value is caught, not blessed by key
    name. A clean input is exactly ``{action_type: <known>, params: <schema-conforming>}``."""
    if not isinstance(inp, dict):
        return _all_strings(inp)                   # an input that is not an object (e.g. a bare string) is prose
    out: list[str] = []
    for key, val in inp.items():
        if key not in ("action_type", "params"):
            out.extend(_all_strings(val))          # the extractor requires EXACTLY {action_type, params}
    action_type = inp.get("action_type")
    schema = PARAM_SCHEMA.get(action_type) if isinstance(action_type, str) else None
    if schema is None:                             # unknown / non-str action_type -> the whole command is untrusted
        out.extend(_all_strings(inp.get("action_type")))
        out.extend(_all_strings(inp.get("params")))
        return out
    params = inp.get("params")
    if not isinstance(params, dict):
        return out + _all_strings(params)
    for pkey, pval in params.items():
        spec = schema.get(pkey)
        if spec is int:
            if isinstance(pval, bool) or not isinstance(pval, int):
                out.extend(_all_strings(pval))     # quantity must be a real int, not a string/container
        elif spec is not None and isinstance(pval, str) and pval in spec:
            continue                               # a valid enum token (e.g. route "r1") is not prose
        else:
            out.extend(_all_strings(pval))         # unknown param key, or a bad/poisoned enum value -> prose
    return out


def _tool_use_prose(block: dict) -> list[str]:
    """Prose carried by a tool_use block: any key outside {type,name,input}, a wrong tool name, or non-command
    input. A clean committed block is exactly {type:"tool_use", name:TOOL_NAME, input:<valid command>}."""
    out: list[str] = []
    for key, val in block.items():
        if key == "type":
            continue
        if key == "name":
            if val != TOOL_NAME:                   # the one tool the extractor matches; a prose name is flagged
                out.extend(_all_strings(val))
        elif key == "input":
            out.extend(_command_input_prose(val))
        else:
            out.extend(_all_strings(val))          # a sibling (scratch) or a stray block id -> prose
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
                out.extend(_all_strings(block))    # a bare string in content[] is prose
            elif block.get("type") in KEPT_BLOCK_TYPES:
                out.extend(_tool_use_prose(block))
            else:                                  # any non-tool_use block: every string except the type tag
                out.extend(_all_strings({k: v for k, v in block.items() if k != "type"}))
    return out


def _project_tool_use(block: dict) -> dict:
    """Project a kept tool_use block to the canonical command skeleton {type,name,input}, dropping siblings
    and a stray block id."""
    return {k: block[k] for k in TOOL_USE_SKELETON_KEYS if k in block}


def redact(wire_bytes: bytes) -> bytes:
    """Return the prose-free committed body: keep ONLY ``tool_use`` content blocks, each PROJECTED to the
    {type,name,input} command skeleton, plus the allowlisted top-level keys; re-serialize deterministically
    (sorted keys). The kept tool_use block(s) flow through the identical extractor. Returns the input
    unchanged if it is not a JSON object."""
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

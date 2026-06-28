"""Strict command extractor (WP-A1a) — the offline agent substrate's parse-or-reject boundary.

The agent layer's ONE seam is the ``commands`` argument to ``turn_record.assemble``. An LLM — or, for the
offline substrate, a HAND-AUTHORED fixture standing in for one — emits a raw provider message body; this
module extracts the typed SEMANTIC choice ``{action_type, params}`` from it, or REJECTS. It decides
WELL-FORMEDNESS ONLY:

  * NOT legality — an out-of-range ``quantity`` or unknown ``route``/``action_type`` extracts fine and is
    then a ``resolver.validate_all`` rejection (a legal-reject is NOT a forfeit).
  * NOT identity — ``actor_id``/``turn``/``command_id`` are bound by the harness downstream and MUST NOT
    appear in the model's output; their presence as a SIBLING of ``action_type``/``params`` is a
    ``semantic-field-invalid`` rejection (the guard is the exact top-level key-set). Identity is read
    downstream only as a sibling field, never out of ``params`` — so an ``actor_id`` buried *inside*
    ``params`` is inert junk (at most a downstream legality reject), not impersonation.

Strict by contract: never take-first on ambiguity, never repair/clamp/coerce. A rejection is a fact, not
a fallback — the caller records an auditable forfeit and the slot resolves via a predeclared NO_OP.

A command arrives as a provider ``tool_use`` block named ``submit_command`` whose ``input`` is exactly
``{action_type: <str>, params: <mapping>}``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from canon import CanonError, canonical_bytes

EXTRACTOR_VERSION = "1"
TOOL_NAME = "submit_command"

# Pinned reject-code enum (well-formedness only). Imported by validate_agent_provenance.py.
REJECT_CODES = (
    "malformed-bytes",         # not UTF-8 / not JSON / not an assistant message with a content list
    "no-command",              # zero submit_command tool_use blocks
    "ambiguous-command",       # >= 2 submit_command tool_use blocks (never take-first)
    "semantic-field-invalid",  # the input is not exactly {action_type: str, params: mapping}
    "non-canon-command",       # {action_type, params} is outside the canon-v1 typed subset (e.g. a float)
)


def project_semantic(command: dict) -> dict:
    """The two fields the model authors — exactly what the binding digest is taken over.

    Defined here ONCE and imported by ``validate_agent_provenance.py`` so the gate and the extractor
    compute the identical projection (the H7 binding rests on this being a single source).
    """
    return {"action_type": command["action_type"], "params": command["params"]}


@dataclass(frozen=True)
class ExtractResult:
    ok: bool
    command: dict | None       # {action_type, params} when ok; None on reject
    reject_code: str | None    # one of REJECT_CODES when not ok; None when ok
    reject_detail: str | None


def _reject(code: str, detail: str) -> ExtractResult:
    return ExtractResult(ok=False, command=None, reject_code=code, reject_detail=detail)


def extract_command(response_bytes: bytes) -> ExtractResult:
    """Parse raw provider response bytes → ``{action_type, params}`` or a pinned rejection."""
    try:
        body = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _reject("malformed-bytes", f"not UTF-8 JSON: {exc}")
    if not isinstance(body, dict) or not isinstance(body.get("content"), list):
        return _reject("malformed-bytes", "not an assistant message with a 'content' list")

    blocks = [
        b for b in body["content"]
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == TOOL_NAME
    ]
    if not blocks:
        return _reject("no-command", f"zero {TOOL_NAME!r} tool_use blocks")
    if len(blocks) > 1:
        return _reject("ambiguous-command",
                       f"{len(blocks)} {TOOL_NAME!r} tool_use blocks (never take-first)")

    payload = blocks[0].get("input")
    if not isinstance(payload, dict):
        return _reject("semantic-field-invalid", "tool_use input is not a mapping")
    if set(payload.keys()) != {"action_type", "params"}:
        return _reject("semantic-field-invalid",
                       f"input keys {sorted(payload.keys())} != ['action_type', 'params'] "
                       "(harness-bound identity must not appear)")
    if not isinstance(payload["action_type"], str):
        return _reject("semantic-field-invalid", "action_type is not a string")
    if not isinstance(payload["params"], dict):
        return _reject("semantic-field-invalid", "params is not a mapping")

    command = {"action_type": payload["action_type"], "params": payload["params"]}
    try:
        canonical_bytes(project_semantic(command))  # reject floats / non-str keys before they enter a digest
    except CanonError as exc:
        return _reject("non-canon-command", str(exc))
    return ExtractResult(ok=True, command=command, reject_code=None, reject_detail=None)

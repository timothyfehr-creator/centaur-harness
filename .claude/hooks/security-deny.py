#!/usr/bin/env python3
"""Centaur PreToolUse guardrail — keep the honesty system un-fakeable.

This is a HOBBY project, so it deliberately carries NO publish/merge ceremony: Claude may
``git push`` / merge freely. The ONE thing this hook still protects is the integrity of the
attestation system — the genuinely interesting part of the harness. An AI tool call must not
silently edit the attestation surface (``attestation_reviewers.yaml`` / ``review.yaml`` /
``signoff.yaml``), because flipping ``attestation_kind: INDEPENDENT`` / ``decision: APPROVED``
by machine would defeat the SYNTHETIC_SELF_CHECK partition that makes "independently attested"
mean something. It also protects its own files so a loop can't quietly disable the guard.

A human edits these files freely — just outside Claude's tools (e.g. in an editor, or via the
``! `` prompt prefix which runs in the user's own shell and is not intercepted here).

HONEST SCOPE: a local hook is a speed-bump, not a cryptographic lock; raw shell can route around
it. It exists to stop the easy/accidental machine edit, nothing more.

CONTRACT (Claude Code hooks reference): a PreToolUse hook reads the tool call as JSON on stdin
and DENIES by printing a ``hookSpecificOutput`` with ``permissionDecision: "deny"`` and exiting 0.
Fails OPEN on malformed input (a schema change must not brick every tool call).
"""
from __future__ import annotations

import json
import os
import sys

# The attestation surface + this guardrail's own config. Matched by BASENAME (paths arrive absolute).
PROTECTED_BASENAMES = {
    "attestation_reviewers.yaml",
    "review.yaml",
    "signoff.yaml",
    "security-deny.py",
    "settings.json",
}


def _deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _protected_paths(tool_name: str, tool_input: dict) -> list[str]:
    """Return the protected file basenames this call would write, if any."""
    candidates: list[str] = []
    if tool_name in ("Edit", "Write"):
        candidates.append(tool_input.get("file_path", ""))
    elif tool_name == "MultiEdit":
        candidates.append(tool_input.get("file_path", ""))
        candidates.extend(e.get("file_path", "") for e in tool_input.get("edits", []) if isinstance(e, dict))
    return [os.path.basename(p) for p in candidates if p and os.path.basename(p) in PROTECTED_BASENAMES]


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # fail OPEN on malformed input

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        sys.exit(0)

    if tool_name in ("Edit", "Write", "MultiEdit"):
        hits = _protected_paths(tool_name, tool_input)
        if hits:
            names = ", ".join(sorted(set(hits)))
            _deny(
                f"Blocked by the Centaur guardrail: '{names}' is a protected file (the attestation "
                f"surface or this guardrail's own config) and must not be edited by an AI tool call — "
                f"faking an independent attestation would corrupt the honesty system. A human may edit "
                f"it outside Claude's tools. See .claude/hooks/security-deny.py."
            )
    sys.exit(0)


if __name__ == "__main__":
    main()

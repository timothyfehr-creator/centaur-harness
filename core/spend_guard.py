"""Token-denominated spend guard (WP-A1b §4.1) — PURE: no network, no clock, no float.

The real bound on a live capture is the call ceiling (``slots * (1 + --max-retries)`` per turn) + a token cap
/ per-game ``$`` cap; this is the PROACTIVE pre-call check (refuse BEFORE a call that could breach the cap, not
after) + a labeled, sourced cost pin for reporting. It lives in a green module so the safety arithmetic is
unit-tested, even though the @live capture script that calls it is out of the green gate.

The proactive check matters: ``max_tokens`` bounds only OUTPUT, and Opus's 1M context means a pathological
prompt is large INPUT in one call. So the per-call ceiling counts ``count_tokens(input) + max_tokens`` and
refuses if it could push cumulative spend to/over the cap.
"""
from __future__ import annotations

# Pinned price, a labeled sourced constant (§4.1). The AUTHORITATIVE cost is the captured `usage` block;
# this is for the proactive ceiling + an advisory estimate only. $/MTok == micro-$ / token, so the estimate
# is exact integer micro-dollars (float-free).
PRICE_MICRO_USD_PER_TOKEN = {"input": 5, "output": 25}   # claude-opus-4-8
PRICE_SOURCE = "claude-api skill / pricing.md"
PRICE_AS_OF = "2026-06-04"
# Default token ceiling for a whole capture run (~$0.50 if it were all output). A pathological large-input
# call has a per-call ceiling above this and is refused; a normal toy-turn call is a few thousand tokens.
DEFAULT_TOKEN_CAP = 20_000


def call_ceiling_tokens(input_tokens: int, max_tokens: int) -> int:
    """Worst-case token spend for ONE call: the counted input + the full output budget."""
    return int(input_tokens) + int(max_tokens)


def affordable(spent_tokens: int, this_call_ceiling: int, token_cap: int) -> bool:
    """True iff this call CANNOT push cumulative spend over the cap (proactive: checked BEFORE the call)."""
    return int(spent_tokens) + int(this_call_ceiling) <= int(token_cap)


def micro_usd(input_tokens: int, output_tokens: int) -> int:
    """Cost in integer MICRO-dollars ($1 = 1_000_000). Float-free: $/MTok == micro-$/token."""
    return (int(input_tokens) * PRICE_MICRO_USD_PER_TOKEN["input"]
            + int(output_tokens) * PRICE_MICRO_USD_PER_TOKEN["output"])


def format_usd(micro: int) -> str:
    """Render micro-dollars as $X.XXXX for a human-readable advisory line (not a committed artifact)."""
    sign = "-" if micro < 0 else ""
    micro = abs(int(micro))
    return f"{sign}${micro // 1_000_000}.{micro % 1_000_000:06d}"

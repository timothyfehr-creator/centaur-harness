"""rng-address-spec-1 — the engine's event-addressed RNG oracle (WP-E1).

A draw's identity is an engine-owned SEMANTIC interaction fingerprint — never any
client ``command_id`` — so resubmitting the same semantic action under a fresh
``command_id`` cannot reroll. The address is canon-v1 encoded and length-framed, so two
distinct addresses cannot collide on one preimage (the round-2 delimiter-injection class
is closed). The ``master_seed`` lives ONLY in the binding below, never inside the address.

Binding (exact, frozen): ``raw = sha256(DOMAIN_TAG || seed:uint64-be || len(addr):uint64-be
|| addr_json)``; ``raw_uint = int.from_bytes(raw[:8], 'big')``; ``d100 = raw_uint % 100`` in
0..99. The modulo bias at 64 bits is ~5e-18 (documented; no rejection sampling for this
UNCALIBRATED slice). Immutable once a golden vector ships: any change is
``rng-address-spec-2``. See docs/ENGINE_CONTRACT.md.
"""
from __future__ import annotations

import hashlib

from canon import canonical_bytes

RNG_ALGORITHM = "sha256-counter"
RNG_ALGORITHM_VERSION = "1"
ADDRESS_SPEC_VERSION = "1"
DOMAIN_TAG = b"centaur/rng-address-spec-1"
DEFAULT_NAMESPACE = "root"

# The address tuple, in declaration order (documentation of the contract; the canonical
# encoding sorts keys, so order here is for humans, not the bytes).
ADDRESS_FIELDS = (
    "turn",
    "phase",
    "actor_id",
    "action_type",
    "target_route",
    "draw_name",
    "draw_index",
    "resolver_id",
    "rng_namespace",
)


class RngError(ValueError):
    """An invalid master_seed or malformed draw address."""


def draw_address(
    *,
    turn: int,
    phase: str,
    actor_id: str,
    action_type: str,
    target_route: str,
    draw_name: str,
    draw_index: int,
    resolver_id: str,
    rng_namespace: str = DEFAULT_NAMESPACE,
) -> dict:
    """Build the canonical semantic draw address.

    Keyword-only and explicit: there is deliberately NO ``command_id`` parameter, so a
    client identifier can never enter the RNG identity.
    """
    return {
        "turn": turn,
        "phase": phase,
        "actor_id": actor_id,
        "action_type": action_type,
        "target_route": target_route,
        "draw_name": draw_name,
        "draw_index": draw_index,
        "resolver_id": resolver_id,
        "rng_namespace": rng_namespace,
    }


def preimage(master_seed: int, address: dict) -> bytes:
    """The exact frozen preimage bytes (domain-separated + length-framed)."""
    if isinstance(master_seed, bool) or not isinstance(master_seed, int):
        raise RngError("master_seed must be an int")
    if master_seed < 0 or master_seed >= 2 ** 64:
        raise RngError("master_seed must be a uint64 (0 <= seed < 2**64)")
    addr_json = canonical_bytes(address)
    return (
        DOMAIN_TAG
        + master_seed.to_bytes(8, "big")
        + len(addr_json).to_bytes(8, "big")
        + addr_json
    )


def draw(master_seed: int, address: dict) -> dict:
    """Return a deterministic draw record ``{raw_uint, d100, address}`` (d100 in 0..99)."""
    raw = hashlib.sha256(preimage(master_seed, address)).digest()
    raw_uint = int.from_bytes(raw[:8], "big")
    return {"raw_uint": raw_uint, "d100": raw_uint % 100, "address": address}

"""Golden + property tests for core/rng.py (rng-address-spec-1, WP-E1).

d100 golden values are sha256 (stdlib) over the frozen, length-framed preimage of a
hand-authored semantic address -- an independent oracle. The key invariants tested:
no client command_id can enter the address (anti-reroll), distinct addresses cannot
collide (length-framing), and the master_seed lives only in the binding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))

import canon  # noqa: E402
import rng  # noqa: E402


def _block_resolve_addr() -> dict:
    return rng.draw_address(
        turn=0,
        phase="resolve",
        actor_id="RED",
        action_type="BLOCK_ROUTE",
        target_route="r1",
        draw_name="block_resolve",
        draw_index=0,
        resolver_id="contested_logistics",
    )


# --- frozen d100 golden values (these select the resolver's success/failure vectors) ---

def test_d100_golden_values() -> None:
    addr = _block_resolve_addr()
    # at threshold 73: seed 0 -> 11 (< 73, block SUCCEEDS) ; seed 3 -> 79 (>= 73, block FAILS)
    assert rng.draw(0, addr)["d100"] == 11
    assert rng.draw(3, addr)["d100"] == 79


def test_d100_in_range() -> None:
    addr = _block_resolve_addr()
    for seed in range(200):
        assert 0 <= rng.draw(seed, addr)["d100"] <= 99


def test_determinism() -> None:
    addr = _block_resolve_addr()
    assert rng.draw(7, addr) == rng.draw(7, addr)


# --- anti-reroll: no client identifier in the RNG identity ---------------------------

def test_address_has_no_command_id() -> None:
    addr = _block_resolve_addr()
    assert set(addr) == set(rng.ADDRESS_FIELDS)
    assert "command_id" not in addr


def test_default_namespace_is_root() -> None:
    assert _block_resolve_addr()["rng_namespace"] == "root"


# --- the binding: seed in one place, addresses cannot collide -----------------------

def test_seed_changes_the_draw() -> None:
    addr = _block_resolve_addr()
    assert rng.draw(0, addr)["raw_uint"] != rng.draw(1, addr)["raw_uint"]


def test_distinct_addresses_distinct_preimage() -> None:
    a = _block_resolve_addr()
    b = dict(a, target_route="r2")
    assert rng.preimage(0, a) != rng.preimage(0, b)


def test_preimage_is_domain_separated_and_length_framed() -> None:
    addr = _block_resolve_addr()
    pre = rng.preimage(0, addr)
    assert pre.startswith(rng.DOMAIN_TAG)
    body = pre[len(rng.DOMAIN_TAG):]
    seed8, len8, addr_json = body[:8], body[8:16], body[16:]
    assert int.from_bytes(seed8, "big") == 0
    assert int.from_bytes(len8, "big") == len(addr_json)
    assert addr_json == canon.canonical_bytes(addr)


@pytest.mark.parametrize("bad", [-1, True, 2 ** 64, "0", 1.0])
def test_invalid_master_seed_rejected(bad: object) -> None:
    with pytest.raises(rng.RngError):
        rng.draw(bad, _block_resolve_addr())

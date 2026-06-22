"""Golden + property tests for core/canon.py (canon-v1, WP-E1).

The byte vectors are HAND-AUTHORED (compact key-sorted JSON is verifiable by eye); the one
sha256 digest is the standard-library hash OF a hand-authored canonical byte string, so it is
an independent oracle, not a value the engine invented for itself.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))

import canon  # noqa: E402


# --- hand-authored canonical byte vectors -------------------------------------------

def test_object_keys_are_sorted() -> None:
    assert canon.canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_list_order_is_preserved_not_sorted() -> None:
    assert canon.canonical_bytes([2, 1]) == b"[2,1]"
    # ordered: reversing a list MUST change the bytes (this is what protects event_batch order)
    assert canon.canonical_bytes([1, 2]) != canon.canonical_bytes([2, 1])


def test_utf8_is_not_ascii_escaped() -> None:
    assert canon.canonical_bytes("café") == b'"caf\xc3\xa9"'


def test_bool_and_null_render_as_json() -> None:
    assert canon.canonical_bytes({"k": True, "n": None}) == b'{"k":true,"n":null}'


def test_bool_and_int_are_distinct() -> None:
    # bool is a subclass of int; canon must still encode them as JSON true / 1
    assert canon.canonical_bytes(True) == b"true"
    assert canon.canonical_bytes(1) == b"1"


def test_determinism() -> None:
    obj = {"z": [1, 2, 3], "a": {"y": "x"}}
    assert canon.canonical_bytes(obj) == canon.canonical_bytes(obj)


# --- the typed-subset guard ---------------------------------------------------------

@pytest.mark.parametrize("bad", [1.5, float("nan"), float("inf"), float("-inf")])
def test_floats_are_rejected(bad: float) -> None:
    with pytest.raises(canon.CanonError):
        canon.canonical_bytes(bad)


def test_nonstring_keys_are_rejected() -> None:
    with pytest.raises(canon.CanonError):
        canon.canonical_bytes({1: "x"})


@pytest.mark.parametrize("bad", [b"bytes", {1, 2}, (1, 2), object()])
def test_unsupported_types_are_rejected(bad: object) -> None:
    with pytest.raises(canon.CanonError):
        canon.canonical_bytes(bad)


def test_nested_float_is_rejected() -> None:
    with pytest.raises(canon.CanonError):
        canon.canonical_bytes({"ok": 1, "bad": [1, 2.0]})


# --- the typed digest (domain: canonical) -------------------------------------------

def test_digest_shape_and_recomputable() -> None:
    # the digest is sha256 of the HAND-AUTHORED canonical bytes -- recomputed independently here
    assert canon.canonical_bytes({"a": 2, "b": 1}) == b'{"a":2,"b":1}'
    assert canon.canonical_digest({"a": 2, "b": 1}) == {
        "algorithm": "sha256",
        "domain": "canonical",
        "value": hashlib.sha256(b'{"a":2,"b":1}').hexdigest(),
    }


def test_digest_is_reformatting_invariant() -> None:
    # logically-equal mappings (different key order) hash equal -- the canonical property,
    # deliberately OPPOSITE to the run-ledger's content-raw digest
    assert canon.canonical_digest({"a": 2, "b": 1}) == canon.canonical_digest({"b": 1, "a": 2})

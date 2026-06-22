"""canon-v1 — the engine's deterministic canonical encoding (WP-E1).

Canonical bytes = compact, key-sorted JSON over a restricted typed value subset
(``None``/``bool``/``int``/``str``/``list``/``dict``), UTF-8, no ASCII escaping.
Floats (and NaN/inf) and any other type are REJECTED — the engine is float-free by
contract, so a float can never silently enter a hashed artifact.

Object KEYS are sorted (a mapping is unordered); LIST ORDER IS PRESERVED — an ordered
sequence such as a turn's ``event_batch`` must keep its order, while unordered
collections (e.g. the accepted command set) are the *caller's* responsibility to sort
BEFORE encoding (see the command-batch sort in docs/ENGINE_CONTRACT.md). canon-v1 itself
never reorders a list.

This ``domain: canonical`` digest is deliberately DISTINCT from the run-ledger's
``content-raw`` raw-bytes digest (which treats reformatting as drift); here, logically
equal values hash equal. Two named functions, two domains — never an untyped ``hash``.

Immutable once a golden vector ships: any change is ``canon-v2``.
"""
from __future__ import annotations

import hashlib
import json

CANON_VERSION = "canon-v1"


class CanonError(ValueError):
    """A value is outside the canon-v1 typed subset (e.g. a float)."""


def _check(value: object) -> None:
    # bool is a subclass of int; both are allowed. float is NOT.
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise CanonError("float is not allowed in canon-v1 (the engine is float-free)")
    if isinstance(value, list):
        for item in value:
            _check(item)
        return
    if isinstance(value, dict):
        for key, val in value.items():
            if not isinstance(key, str):
                raise CanonError(
                    f"canon-v1 object keys must be strings, got {type(key).__name__}"
                )
            _check(val)
        return
    raise CanonError(f"canon-v1 does not allow values of type {type(value).__name__}")


def canonical_bytes(value: object) -> bytes:
    """Return the canon-v1 UTF-8 bytes of a typed value.

    Raises ``CanonError`` for any off-subset value (float, bytes, set, non-str key, ...).
    Object keys are sorted; list order is preserved.
    """
    _check(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_digest(value: object) -> dict:
    """Return a typed digest ``{algorithm, domain, value}`` over canon-v1 bytes."""
    return {
        "algorithm": "sha256",
        "domain": "canonical",
        "value": hashlib.sha256(canonical_bytes(value)).hexdigest(),
    }

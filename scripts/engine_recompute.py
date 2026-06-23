#!/usr/bin/env python3
"""Deterministic engine recompute for the contested-logistics slice (WP-E1).

A self-contained recompute entrypoint: assemble the slice turn record for a given seed and print its
canon-v1 sha256. Used by the PASS#2 fresh-subprocess determinism check (output must be identical
regardless of PYTHONHASHSEED) and as the recomputation basis for the turn-replay gate. Deterministic;
the only output is the hash on stdout. The runtime fingerprint is FIXED here so recompute is
byte-stable; the live git fingerprint is the real engine run's concern (engine_run, Increment 7).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import canon  # noqa: E402
import turn_record as tr  # noqa: E402

FIXED_FINGERPRINT = {"engine_source_hash": "wpe1-slice", "python": "fixed", "pyyaml_version": "fixed",
                     "serializer_version": "1", "persistence_profile": "local-posix-fs-v1"}


def slice_state(threshold: int = 73) -> dict:
    return {"schema_version": "1.0", "state": {"as_of_turn": 0, "entities": [
        {"id": "blue_supply", "type": "FORCE", "fields": {
            "origin": {"value": 100, "unit": "units"}, "in_transit": {"value": 0, "unit": "units"},
            "delivered": {"value": 0, "unit": "units"}, "loss_sink": {"value": 0, "unit": "units"}}},
        {"id": "route:r1", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": True, "unit": "bool"}}},
        {"id": "route:r2", "type": "ROUTE", "fields": {
            "capacity": {"value": 50, "unit": "units"}, "blockable": {"value": False, "unit": "bool"}}},
        {"id": "route_secret:r1", "type": "ROUTE_SECRET", "fields": {
            "subject_route": {"value": "r1", "unit": "id"},
            "block_threshold": {"value": threshold, "unit": "d100"}}}]}}


def slice_commands() -> list:
    return [
        {"command_id": "cmd-blue-1", "turn": 0, "actor_id": "BLUE", "action_type": "DISPATCH_SUPPLY",
         "params": {"quantity": 30, "route": "r1"}},
        {"command_id": "cmd-red-1", "turn": 0, "actor_id": "RED", "action_type": "BLOCK_ROUTE",
         "params": {"route": "r1"}}]


def assemble_slice(seed: int, threshold: int = 73, commands: list | None = None) -> dict:
    return tr.assemble(turn=0, start_state=slice_state(threshold),
                       commands=slice_commands() if commands is None else commands,
                       master_seed=seed, runtime_fingerprint=FIXED_FINGERPRINT,
                       successor_slot="run/turns/0000.json")


def canon_sha(seed: int) -> str:
    rec = assemble_slice(seed)["turn_record"]
    return hashlib.sha256(canon.canonical_bytes(rec)).hexdigest()


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine_recompute.py", description="Deterministic slice recompute.")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    print(canon_sha(args.seed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

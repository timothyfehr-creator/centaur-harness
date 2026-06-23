"""WP-E2a salvo run + recompute.

Loads the homogeneous-salvo scenario (engine_state.yaml + rules.yaml), assembles the deterministic
turn record via the salvo resolver, and either writes the committed record (``--write``) or prints its
canon-v1 sha256 (default — used by the PASS#2 fresh-subprocess determinism check). The ruleset passed
to the engine is the int-only ``{param: value}`` extracted from rules.yaml (the `source` provenance
stays in rules.yaml). Fixed fingerprint -> byte-stable; UNCALIBRATED placeholder data.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import canon  # noqa: E402
import salvo_resolver as salvo  # noqa: E402
import turn_record as tr  # noqa: E402

SCENARIO = ROOT / "examples" / "ru_ua_salvo_homogeneous"
FIXED_FINGERPRINT = {"engine_source_hash": "wpe2a-salvo", "python": "fixed", "pyyaml_version": "fixed",
                     "serializer_version": "1", "persistence_profile": "local-posix-fs-v1"}


def load_scenario() -> tuple[dict, dict]:
    state = yaml.safe_load((SCENARIO / "engine_state.yaml").read_text(encoding="utf-8"))
    rules_doc = yaml.safe_load((SCENARIO / "rules.yaml").read_text(encoding="utf-8"))
    ruleset = {name: spec["value"] for name, spec in rules_doc["params"].items()}   # int-only
    return state, ruleset


def assemble() -> dict:
    state, ruleset = load_scenario()
    return tr.assemble(turn=0, start_state=state, commands=[], master_seed=0,
                       runtime_fingerprint=FIXED_FINGERPRINT, successor_slot="run/turns/0000.json",
                       ruleset=ruleset, resolver=salvo)


def canon_sha() -> str:
    return hashlib.sha256(canon.canonical_bytes(assemble()["turn_record"])).hexdigest()


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="salvo_run.py")
    parser.add_argument("--write", action="store_true", help="write the committed turn record")
    args = parser.parse_args(argv)
    record = assemble()["turn_record"]
    if args.write:
        slot = SCENARIO / "run" / "turns" / "0000.json"
        slot.parent.mkdir(parents=True, exist_ok=True)
        slot.write_bytes(canon.canonical_bytes(record))
        print(f"wrote {slot.relative_to(ROOT)} (turn {record['turn']}, {len(record['event_batch'])} events)")
    else:
        print(canon_sha())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

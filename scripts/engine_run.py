"""Engine run for the contested-logistics slice (WP-E1): assemble + write a committed turn record.

Writes the canon-v1 bytes of the slice's turn record to the scenario's ``run/turns/`` tree. The
fingerprint is fixed (via engine_recompute), so the committed record record-replays and recomputes
byte-identically — which is what the turn-replay gate verifies. Usage: python scripts/engine_run.py
[--seed N].
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import canon  # noqa: E402
import engine_recompute as er  # noqa: E402

SCENARIO = Path(__file__).resolve().parent.parent / "examples" / "contested_logistics_abstract"


def run(seed: int = 0) -> tuple[Path, dict]:
    record = er.assemble_slice(seed)["turn_record"]
    slot = SCENARIO / "run" / "turns" / "0000.json"
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.write_bytes(canon.canonical_bytes(record))
    return slot, record


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="engine_run.py")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    slot, record = run(args.seed)
    print(f"wrote {slot.relative_to(SCENARIO.parent.parent)} "
          f"(turn {record['turn']}, {len(record['event_batch'])} events, "
          f"{'1 draw' if record['rng'] else 'no draw'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

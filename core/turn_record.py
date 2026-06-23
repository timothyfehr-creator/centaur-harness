"""Turn-record assembly + commit (WP-E1) — the single durable authority.

A committed turn record is the one durable byte object from which engine_state, projections, and
all replay tiers are DERIVED. This module assembles it from a resolver ``transition()`` result and
commits it to a single-successor slot. The ``transition_input_hash`` (the idempotency key) is a
canon-v1 digest over the CAUSAL inputs only, with ``rng`` null when no draw was consumed — so a
no-draw turn is seed-independent. See docs/ENGINE_CONTRACT.md.
"""
from __future__ import annotations

import platform
import subprocess

import yaml  # for the pyyaml version stamp only

import resolver as rsv
import rng
from atomic import PERSISTENCE_PROFILE, commit_new_slot
from canon import CANON_VERSION, canonical_bytes, canonical_digest

ENGINE_SCHEMA_VERSIONS = {
    "engine_state": "1.0",
    "engine_command": "1.0",
    "transition_event": "1.0",
    "turn_record": "1.0",
}
SERIALIZER_VERSION = "1"


def seal_state(state_obj: dict) -> dict:
    """Return a state ENVELOPE ``{schema_version, state, state_digest}`` with ``state_digest`` computed
    over the ``state`` field ONLY (self-reference excluded, per ENGINE_CONTRACT.md C7). Idempotent."""
    inner = state_obj["state"]
    return {
        "schema_version": state_obj.get("schema_version", ENGINE_SCHEMA_VERSIONS["engine_state"]),
        "state": inner,
        "state_digest": canonical_digest(inner),   # domain:canonical, over the state field only
    }


def rng_request(draws: list, master_seed: int):
    """The RNG request block, or ``None`` when no draw was consumed (no decorative seed)."""
    if not draws:
        return None
    return {
        "master_seed": master_seed,
        "algorithm": rng.RNG_ALGORITHM,
        "algorithm_version": rng.RNG_ALGORITHM_VERSION,
        "address_spec_version": rng.ADDRESS_SPEC_VERSION,
        "rng_namespace": rng.DEFAULT_NAMESPACE,
        "ordered_draw_addresses": [d["address"] for d in draws],
    }


def transition_input_hash(start_state: dict, sorted_commands: list, request,
                          resolver=rsv, ruleset: object = None) -> str:
    """canon-v1 digest over the causal inputs (the idempotency key / candidate_id)."""
    preimage = {
        "start_state": start_state,
        "command_batch": sorted_commands,
        "ruleset_version": resolver.RULESET_VERSION,
        "resolver_id": resolver.RESOLVER_ID,
        "resolver_version": resolver.RESOLVER_VERSION,
        "ruleset": ruleset,                     # None for the logistics resolver; int-only params otherwise
        "rng_request": request,                 # None when no draw -> seed-independent
        "schema_versions": ENGINE_SCHEMA_VERSIONS,
        "canon_version": CANON_VERSION,
    }
    return canonical_digest(preimage)["value"]


def compute_runtime_fingerprint(repo_dir: str = ".") -> dict:
    """Compact provenance: git commit(+dirty) + python + pyyaml + serializer + persistence profile."""
    source = "unknown"
    try:
        sha = subprocess.run(["git", "-C", repo_dir, "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", repo_dir, "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip()
        source = f"{sha}{'-dirty' if dirty else ''}"
    except Exception:
        source = "unknown"
    return {
        "engine_source_hash": source,
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "pyyaml_version": getattr(yaml, "__version__", "unknown"),
        "serializer_version": SERIALIZER_VERSION,
        "persistence_profile": PERSISTENCE_PROFILE,
    }


def assemble(*, turn: int, start_state: dict, commands: list, master_seed: int,
             runtime_fingerprint: dict, successor_slot: str, ruleset: object = None,
             resolver=rsv) -> dict:
    """Resolve the turn and assemble the record. A REJECTED turn yields NO record (status only).

    ``resolver`` selects the resolver module (defaults to the contested-logistics one); any module with
    the interface {RESOLVER_ID, RESOLVER_VERSION, RULESET_VERSION, validate_all, sort_commands,
    transition, reduce} plugs in. ``ruleset`` (int-only params, or None) is stored in the record so
    replay/recomputation is self-contained."""
    result = resolver.transition(start_state, commands, master_seed=master_seed, turn=turn, ruleset=ruleset)
    if result["status"] == "rejected":
        return {"status": "rejected", "rejections": result["rejections"], "turn_record": None}

    accepted, _ = resolver.validate_all(commands, start_state, ruleset)
    sorted_commands = resolver.sort_commands(accepted)
    request = rng_request(result["draws"], master_seed)
    sealed_start = seal_state(start_state)              # {schema_version, state, state_digest}
    sealed_result = seal_state(result["resulting_state"])
    record = {
        "schema_version": ENGINE_SCHEMA_VERSIONS["turn_record"],
        "turn": turn,
        "transition_input_hash": transition_input_hash(sealed_start, sorted_commands, request, resolver, ruleset),
        "start_state": sealed_start,
        "ruleset_version": resolver.RULESET_VERSION,
        "resolver_id": resolver.RESOLVER_ID,
        "resolver_version": resolver.RESOLVER_VERSION,
        "ruleset": ruleset,
        "rng": request,
        "command_batch": sorted_commands,
        "event_batch": result["events"],
        "draw_records": result["draws"],
        "resulting_state": sealed_result,
        "digests": {                                   # state parts: the state_digest (over the state
            "start_state": sealed_start["state_digest"],      # field only); batches: over their bytes
            "command_batch": canonical_digest(sorted_commands),
            "event_batch": canonical_digest(result["events"]),
            "resulting_state": sealed_result["state_digest"],
        },
        "runtime_fingerprint": runtime_fingerprint,
        "successor_slot": successor_slot,
    }
    return {"status": "resolved", "turn_record": record}


def commit(record: dict, slot_path: str) -> str:
    """Commit a turn record to its single-successor slot (canon bytes, O_EXCL, byte-identical-or-fail)."""
    return commit_new_slot(slot_path, canonical_bytes(record))

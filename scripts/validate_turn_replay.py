#!/usr/bin/env python3
"""Turn-replay gate (WP-E1) — record-replay + recomputation over committed turn records.

Globs ``examples/**/run/turns/*.json``. For each committed turn record:
  - record-replay: ``reduce(start_state, event_batch)`` reproduces the committed resulting state
    (matched on the ``state_digest`` over the state field).
  - recomputation: re-running the resolver from ``start_state`` + ``command_batch`` + the recorded
    seed reproduces the same ``event_batch`` and resulting state, byte-identically.
  - structural: ``rng`` is null iff no draw was consumed; every stochastic terminal references a draw.

Exit codes: 0 = all verified, 1 = finding(s), 2 = usage / fail-closed (no records found / unreadable).
Findings to stderr as ``  - {code}  {where}  {msg}``. Matches the validator convention.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import agent_logistics as agent_log  # noqa: E402
import canon  # noqa: E402
import resolver as rsv  # noqa: E402
import salvo_resolver as salvo  # noqa: E402
import salvo_resolver_het as salvo_het  # noqa: E402
import turn_record as tr  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
# Resolver registry: replay/recompute is dispatched by the record's resolver_id (a literal lookup). Each
# resolver declares its STOCHASTIC_TERMINALS (logistics has draws; the deterministic salvos do not), read
# below for the draw->event coherence check.
_RESOLVERS = {rsv.RESOLVER_ID: rsv, salvo.RESOLVER_ID: salvo, salvo_het.RESOLVER_ID: salvo_het,
              agent_log.RESOLVER_ID: agent_log}


def check_record(rec: dict, where: str) -> list:
    problems: list = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    has_draws = bool(rec.get("draw_records"))
    if has_draws and rec.get("rng") is None:
        add("rng-missing", "draw_records present but rng block is null")
    if not has_draws and rec.get("rng") is not None:
        add("decorative-seed", "rng block present but no draw was consumed")

    # self-binding integrity: each sealed envelope's state_digest MUST equal a fresh digest of its OWN
    # `state`. Without this, the chain head-handoff (digest == digest) plus an attacker-recomputable
    # transition_input_hash would let a FABRICATED start_state.state slip through both gates -- the digest
    # is then just an unverified claim. (adversarial-verify HOLE 1; applies to single- and multi-turn.)
    for envk in ("start_state", "resulting_state"):
        env = rec.get(envk) or {}
        try:
            expected = canon.canonical_digest(env.get("state"))
        except canon.CanonError as exc:    # a non-canon (e.g. float) state can't be a sealed engine state
            add("state-digest-self-mismatch", f"{envk}.state is not canon-encodable ({exc})")
            continue
        if expected != env.get("state_digest"):
            add("state-digest-self-mismatch",
                f"{envk}.state_digest != canonical_digest({envk}.state) (self-binding broken)")

    resolver = _RESOLVERS.get(rec.get("resolver_id"))        # dispatch by resolver_id
    if resolver is None:                                     # fail-closed: never substitute a default (EC-2)
        add("unknown-resolver-id",
            f"resolver_id {rec.get('resolver_id')!r} is not registered; refusing to replay")
        return problems
    ruleset = rec.get("ruleset")                              # int-only params, or None (logistics)

    # idempotency-key integrity (EC-1): the committed transition_input_hash MUST equal a fresh recompute
    # from the record's OWN causal inputs. Catches a STALE committed record -- e.g. one written before a
    # preimage change (the `ruleset` field) -- that record-replay + recomputation would otherwise pass.
    recomputed_tih = tr.transition_input_hash(
        rec["start_state"], rec["command_batch"], rec.get("rng"), resolver, ruleset)
    if rec.get("transition_input_hash") != recomputed_tih:
        add("transition-input-hash-mismatch",
            f"committed transition_input_hash {str(rec.get('transition_input_hash'))[:12]}... != recompute "
            f"{recomputed_tih[:12]}... -- stale record; committed bytes no longer match the engine")

    # record-replay
    try:
        rederived = resolver.reduce(rec["start_state"], rec["event_batch"])
    except Exception as exc:  # noqa: BLE001
        add("reduce-failed", f"reduce raised: {exc}")
        return problems
    if canon.canonical_digest(rederived["state"]) != rec["resulting_state"]["state_digest"]:
        add("replay-mismatch", "reduce(start_state, event_batch) != committed resulting_state")

    # recomputation
    seed = rec["rng"]["master_seed"] if rec.get("rng") else 0
    try:
        recomputed = resolver.transition(rec["start_state"], rec["command_batch"],
                                         master_seed=seed, turn=rec["turn"], ruleset=ruleset)
    except Exception as exc:  # noqa: BLE001
        add("recompute-failed", f"transition raised: {exc}")
        return problems
    if canon.canonical_bytes(recomputed["events"]) != canon.canonical_bytes(rec["event_batch"]):
        add("recompute-event-mismatch", "recomputed event_batch != committed")
    if canon.canonical_bytes(recomputed["resulting_state"]["state"]) \
            != canon.canonical_bytes(rec["resulting_state"]["state"]):
        add("recompute-state-mismatch", "recomputed resulting state != committed")

    # draw -> event coherence: each stochastic terminal references exactly one draw, and vice versa. The
    # stochastic-terminal event types are RESOLVER-declared, so the check is correct per resolver (vacuous
    # for the deterministic salvos -- 0 terminals, 0 draws) rather than coincidentally passing.
    terminals = getattr(resolver, "STOCHASTIC_TERMINALS", ())
    stochastic = [e for e in rec["event_batch"] if e["event_type"] in terminals and e.get("draw_ref")]
    if len(stochastic) != len(rec.get("draw_records", [])):
        add("draw-event-count", "stochastic-terminal count != draw count")
    return problems


def check_chain(group: list) -> list:
    """Cross-record CONTINUITY of one scenario's run/turns chain (WP-E2b2). ``group`` is the scenario's
    records as ``[(where, path, rec)]`` sorted by filename. A LENGTH-1 group is a single-turn scenario ->
    a no-op (so existing single-turn scenarios are unaffected). For a multi-turn chain it asserts: ordered
    + gap-free (file i is ``{i:04d}.json``, its record's turn is i); a BYTE-IDENTICAL head handoff
    (``start_state(i).state_digest == resulting_state(i-1).state_digest`` -- clean because ``reduce``
    advances ``as_of_turn``); monotone ``as_of_turn``; the ``successor_slot`` forward pointer; and one
    resolver + ruleset across the chain."""
    problems: list = []
    if len(group) < 2:
        return problems
    where0 = group[0][0]

    def add(code: str, msg: str) -> None:
        problems.append((code, where0, msg))

    for i, (_where, path, rec) in enumerate(group):
        if path.stem != f"{i:04d}":
            add("chain-gap", f"expected run/turns/{i:04d}.json, found {path.name} at position {i}")
            return problems   # a broken sequence makes the rest meaningless
        if rec.get("turn") != i:
            add("chain-turn-nonmonotone", f"{path.name}: record turn {rec.get('turn')} != position {i}")

    first = group[0][2]
    ident = (first.get("resolver_id"), first.get("resolver_version"), first.get("ruleset"))
    for i in range(1, len(group)):
        prev, cur = group[i - 1][2], group[i][2]
        if cur["start_state"]["state_digest"] != prev["resulting_state"]["state_digest"]:
            add("chain-head-mismatch",
                f"week {i} start_state != week {i - 1} resulting_state (head handoff not byte-identical)")
        if cur["start_state"]["state"]["as_of_turn"] != i:
            add("chain-turn-nonmonotone", f"week {i} start_state as_of_turn != {i}")
        if cur["resulting_state"]["state"]["as_of_turn"] != cur["start_state"]["state"]["as_of_turn"] + 1:
            add("chain-turn-nonmonotone", f"week {i} resulting as_of_turn != start as_of_turn + 1")
        if (cur.get("resolver_id"), cur.get("resolver_version"), cur.get("ruleset")) != ident:
            add("chain-resolver-switch", f"week {i} resolver_id/version/ruleset differs from week 0")
    for i in range(len(group) - 1):
        rec = group[i][2]
        if rec.get("successor_slot") != f"run/turns/{i + 1:04d}.json":
            add("chain-successor-mismatch",
                f"week {i} successor_slot {rec.get('successor_slot')!r} != run/turns/{i + 1:04d}.json")
    return problems


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate_turn_replay.py")
    parser.add_argument("paths", nargs="*",
                        help="turn-record files (default: glob examples/**/run/turns/*.json)")
    args = parser.parse_args(argv)
    files = [Path(p) for p in args.paths] if args.paths \
        else sorted(REPO_ROOT.glob("examples/**/run/turns/*.json"))
    if not files:
        print("error: no committed turn records (examples/**/run/turns/*.json); refusing to report clean.",
              file=sys.stderr)
        return 2

    loaded: list = []   # (where, path, rec)
    for path in files:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"error: cannot read {path}: {exc}; refusing to report clean.", file=sys.stderr)
            return 2
        try:
            where = str(path.relative_to(REPO_ROOT))
        except ValueError:
            where = str(path)
        loaded.append((where, path, rec))

    findings: list = []
    for where, _path, rec in loaded:
        findings.extend(check_record(rec, where))      # per-record replay + recompute + idempotency hash

    # chain pass (WP-E2b2): group records by their run/turns dir; each group is one campaign chain.
    groups: dict = {}
    for where, path, rec in loaded:
        groups.setdefault(path.parent, []).append((where, path, rec))
    for parent in sorted(groups):
        findings.extend(check_chain(sorted(groups[parent], key=lambda t: t[1].name)))

    if findings:
        print(f"turn-replay FAILED: {len(findings)} problem(s):", file=sys.stderr)
        for code, where, msg in findings:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1
    print(f"turn-replay OK ({len(files)} turn record(s) replayed + recomputed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Centaur agent fog no-leak validator (WP-A1a) — the differential fog gate.

For every committed agent turn record (an `agent_logistics` record with BLUE/RED players), this gate
asserts each player's fog-of-war view (`engine_projection.project_turn_record`) leaks no hidden state.
Three checks per viewer:

  STRUCTURAL: the view carries no ROUTE_SECRET entity (the hidden block_threshold container is gone),
     its keys are exactly the fixed allowlist, and BLUE never sees a ROUTE_BLOCK_ATTEMPTED (an opponent's
     failed block is invisible).
  CANARY: the long, unique hidden VALUES (each draw's raw_uint, the full-state digests) never appear
     verbatim in the view bytes. (A bare block_threshold int is covered structurally, not by canary --
     a short int matches by chance inside a sha256 hex digest.)
  DIFFERENTIAL (the strong proof): re-resolve the committed turn across EVERY block_threshold 0..99 and
     group the viewer's projection by terminal OUTCOME; within each outcome group the projections must be
     BYTE-IDENTICAL. The viewer is allowed to see the OUTCOME (its supply's fate) but never the threshold
     VALUE that produced it -- so the view is a function of (public state, outcome), never of the secret.

Certificate wording: "hidden state never entered the view" -- never "no leak" (the gate checks these
specific surfaces, not an unbounded space). STRUCTURAL only. Composed into `verify.py --mode release`.

Usage:
    python scripts/validate_agent_fog.py                    # sweep examples/**/run/turns/*.json
    python scripts/validate_agent_fog.py --scenario-dir DIR # one scenario's records

Exit codes: 0 = ok (no leak, or no agent records), 1 = findings, 2 = usage / fail-closed (unreadable).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import agent_logistics as al  # noqa: E402
import canon  # noqa: E402
import engine_projection as ep  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_RESOLVER_ID = al.RESOLVER_ID
VIEWERS = ("BLUE", "RED")
AGENT_VIEW_KEYS = {"viewer", "turn", "state", "events", "projection_digest"}
# Adjudicator-only EVENT keys that must never surface in an agent view. The canary covers long VALUES;
# this covers the SHORT draw-derived ones (d100, master_seed) the canary can't reliably match -- a
# projector regression that copied one onto a view event would slip past both the canary and the
# fixed-d100 differential, so it is named structurally here.
DRAW_EVENT_KEYS = {"draw_ref", "raw_uint", "d100", "master_seed", "source_command_id", "event_id"}


def _hidden_values(rec: dict) -> list[str]:
    """The long, unique hidden values that must never appear verbatim in any agent view."""
    vals = [rec["start_state"]["state_digest"]["value"], rec["resulting_state"]["state_digest"]["value"]]
    for d in rec.get("draw_records", []):
        vals.append(str(d["raw_uint"]))   # the 64-bit raw draw (unique; not a chance sha256 substring)
    return vals


def _reresolve_view(rec: dict, threshold: int, viewer: str) -> tuple[str, bytes]:
    """Re-resolve the committed turn with a counterfactual block_threshold; return (outcome, view bytes)."""
    start = copy.deepcopy(rec["start_state"])
    for ent in start["state"]["entities"]:
        if ent["type"] == "ROUTE_SECRET":
            ent["fields"]["block_threshold"]["value"] = threshold
    seed = rec["rng"]["master_seed"] if rec.get("rng") else 0
    out = al.transition(start, rec["command_batch"], master_seed=seed, turn=rec["turn"])
    record_like = {"turn": rec["turn"], "resulting_state": out["resulting_state"], "event_batch": out["events"]}
    outcome = next((e["event_type"] for e in out["events"]
                    if e["event_type"] in ("SUPPLY_DELIVERED", "SUPPLY_LOST")), "none")
    return outcome, canon.canonical_bytes(ep.project_turn_record(viewer, record_like))


def _leak_problems(rec: dict, where: str) -> list[tuple[str, str, str]]:
    """No-leak findings for ONE committed turn record across both viewers (unit-testable core)."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    for viewer in VIEWERS:
        view = ep.project_turn_record(viewer, rec)
        # STRUCTURAL
        if set(view.keys()) != AGENT_VIEW_KEYS:
            add("view-keys-not-allowlisted", f"{viewer} view keys {sorted(view.keys())} != {sorted(AGENT_VIEW_KEYS)}")
        if any(e.get("type") == "ROUTE_SECRET" for e in view["state"]["state"]["entities"]):
            add("route-secret-in-view", f"{viewer} view contains a ROUTE_SECRET entity (the hidden threshold)")
        if viewer == "BLUE" and any(e["event_type"] == "ROUTE_BLOCK_ATTEMPTED" for e in view["events"]):
            add("opponent-action-in-view", "BLUE view contains RED's ROUTE_BLOCK_ATTEMPTED (a failed block must be invisible)")
        for ev in view["events"]:
            leaked = DRAW_EVENT_KEYS & set(ev.keys())
            if leaked:
                add("draw-field-in-view", f"{viewer} view event carries adjudicator-only key(s) {sorted(leaked)}")
        # CANARY
        view_bytes = canon.canonical_bytes(view)
        text = view_bytes.decode("utf-8")
        for hv in _hidden_values(rec):
            if hv in text:
                add("hidden-value-verbatim", f"{viewer} view contains the hidden value {hv[:16]}... verbatim")
        # DIFFERENTIAL: view is invariant under the threshold VALUE at a fixed OUTCOME
        by_outcome: dict = {}
        for t in range(100):
            outcome, vb = _reresolve_view(rec, t, viewer)
            by_outcome.setdefault(outcome, set()).add(vb)
        for outcome, views in by_outcome.items():
            if len(views) != 1:
                add("threshold-leaks-into-view",
                    f"{viewer} view is NOT invariant under block_threshold at fixed outcome {outcome!r} "
                    f"({len(views)} distinct views) -- the secret threshold value leaks into the view")
    return problems


def _agent_records(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.glob("**/run/turns/*.json")):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("resolver_id") == AGENT_RESOLVER_ID:
                out.append(p)
        except Exception:  # noqa: BLE001
            out.append(p)   # an unreadable agent-area record is surfaced (fail-closed) below
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate_agent_fog.py",
                                     description="Differential fog no-leak check over committed agent records.")
    parser.add_argument("--scenario-dir", default=None,
                        help="one scenario's records (default: sweep examples/**/run/turns/*.json)")
    args = parser.parse_args(argv)
    root = Path(args.scenario_dir).resolve() if args.scenario_dir else REPO_ROOT / "examples"
    records = _agent_records(root)
    if not records:
        print("agent-fog OK (no agent records present)")
        return 0
    problems: list[tuple[str, str, str]] = []
    for path in records:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"error: cannot read {path}: {exc}; refusing to report clean.", file=sys.stderr)
            return 2
        where = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
        problems.extend(_leak_problems(rec, where))
    if problems:
        print(f"agent-fog FAILED: {len(problems)} problem(s):", file=sys.stderr)
        for code, where, msg in problems:
            print(f"  - {code}  {where}  {msg}", file=sys.stderr)
        return 1
    print(f"agent-fog OK ({len(records)} agent record(s); hidden state never entered any view)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

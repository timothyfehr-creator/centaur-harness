# CLAUDE.md — Centaur Harness

Project guidance for Claude Code. This supplements the global principles and the
shared agent rules in [AGENTS.md](AGENTS.md). Read
[IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md) before editing.

## Mission anchor

- **Purpose:** produce a disciplined, verifiable harness whose gates prevent
  unsourced, unsafe, malformed, unreviewed, or non-reproducible outputs from
  appearing valid.
- **Primary artifact:** `scripts/verify.py` and the gates it composes — `scaffold`
  (repo integrity + scenario schema) and `draft` (WP4: scaffold + the source / claim /
  event / state / agent-grounding / safety gates, reporting active vs not-yet-implemented
  checks, STRUCTURAL ONLY) and `release` (WP8–9: draft's checks + the run-ledger + the
  review/signoff attestation + the calibration record; STRUCTURAL + ATTESTATION ONLY; propagates
  the worst gate exit code, so it never falsely passes). Each evidence/safety gate also runs as a
  standalone CI step; WP7 adds the reproducibility **run-ledger** gate (`scripts/validate_run_ledger.py`
  — a fail-closed lockfile drift check, a CI step, deliberately **not** in `draft`), WP8 adds the
  **review + signoff** attestation gate (`scripts/validate_review_signoff.py`), WP9 adds the
  **calibration** evidence-or-label gate (`scripts/validate_calibration.py` — a §5 record gate, the
  12th gate, composed into `release`), and WP6 adds the fog-of-war **context compiler**
  (`core/context_compiler.py` — a deterministic library, not a gate). The enforceable-plumbing phase
  (0–9) is complete; the wargame engine is the next, separate effort.
- **Non-goals (for now):** a full AI-vs-AI wargame engine, institutional
  governance, multi-run orchestration, dashboards, calibration suites, OSINT
  ingestion, a release-ready scenario. See the plan's Non-goals.

## How to work here

- Build enforceable plumbing before engine logic (plan §3 sequencing).
- Implement one work package at a time; verify and review before the next.
- Keep `scaffold` mode repo-level and lightweight. Do not make it depend on a
  fully sourced scenario.
- `draft` mode (WP4) composes scaffold + the evidence/safety gates and is STRUCTURAL
  ONLY — it must report which checks are active vs not-yet-implemented and must never
  imply analytical validity. `release` mode (WP8-9) composes draft + the run-ledger + the
  review/signoff attestation + the calibration record; it is STRUCTURAL + ATTESTATION ONLY and
  propagates the worst gate exit code (findings → 1, a gate that cannot run → 2), so it never
  falsely passes.
- The reproducibility ledger (`run_ledger.yaml`, WP7) is a **lockfile**: any change to a
  declared input (`factbase/*`, `knowledge/**`, a scenario's `state/private/*` or root files)
  requires re-running `scripts/validate_run_ledger.py --write` and committing the refreshed
  ledger, or CI fails closed on the drift. The WP8 attestations (`review.yaml` + `signoff.yaml`)
  and a WP9 `calibration.yaml` record pin the same `code_version`, so a declared-input change also
  means re-review / re-sign / re-score (update their `code_version`), or the `release` gate fails
  `stale-attestation` / `stale-calibration`. See [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Commands

```bash
python scripts/verify.py --mode scaffold   # repo-level integrity
python scripts/verify.py --mode draft      # scaffold + evidence/safety gates (STRUCTURAL ONLY)
python scripts/verify.py                    # defaults to scaffold
pytest                                       # test suite
```

(No `python` binary on the local machine — use `python3` locally; CI provides
`python`.)

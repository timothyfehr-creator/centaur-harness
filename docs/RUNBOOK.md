# Runbook — the Centaur work-package delivery loop

How a work package (WP) gets built here. This codifies the proven, gated cadence so a longer
run — or any fresh session/agent — stays disciplined and reproducible. It is the durable form
of AGENTS.md's "Standard loop". Read [CONSTITUTION.md](CONSTITUTION.md) for the commitments,
[../CLAUDE.md](../CLAUDE.md) for the mission anchor, and [../AGENTS.md](../AGENTS.md) for the
operating rules; this file is the *process*.

## The per-WP loop

1. **PLAN** (plan mode). Read the WP's spec in `../IMPLEMENTATION_PLAN_V2.md` + the current
   code. Run a **research + design + red-team** pass (parallel "explore the repo" + "design
   intent", then a concrete design, then an adversarial critique) **verified against the live
   repo** — not from memory. Ask the user only the *genuine* design decisions (1–3: enums,
   scope, architecture forks). Write the plan (Context · settled decisions · the design ·
   files · verification · anti-overbuild). Get approval before editing code.
2. **IMPLEMENT.** Search before building — mirror existing patterns and reuse helpers
   (`load_registry`, `_usable_registry`, `_validate_skeleton`, `_id_set`, …). Gates are
   standalone and **fail closed** (exit `0` clean / `1` findings / `2` usage-or-fail-closed).
   Fixtures are **single-fault** (each invalid fixture fails for exactly one code; otherwise
   fully valid). All example/fixture content is **SYNTHETIC / ILLUSTRATIVE** — never a
   fabricated real-world fact — and **secret-scan-clean**.
3. **VERIFY locally** (via `.venv`): the new gate's CLI (clean run + each fixture) ·
   `verify.py --mode draft` · `--mode scaffold` · `safety_check.py` · `secret_scan.py` · full
   `pytest`. Everything green.
4. **ADVERSARIAL REVIEW** *before* committing: an independent review pass (2–3 reviewers over
   distinct dimensions — correctness/single-fault, fail-closed/scope, honesty/docs — plus a
   synthesis with an ACCEPT/REVISE verdict). Fold in blockers and worthwhile nits; re-verify.
5. **COMMIT** atomically — the feature commit leaves the tree green; one logical change per
   commit; end the message with the `Co-Authored-By:` + `Claude-Session:` trailers. Push, then
   **watch CI go green** and confirm the new step actually ran.
6. **LEDGER.** Add the WP entry to [PROGRESS.md](PROGRESS.md) (acceptance table, decisions,
   commit + CI run), drop it from *Deferred*, and reconcile `../IMPLEMENTATION_PLAN_V2.md`
   (mark the WP delivered; advance the "next" pointer). Commit; push; CI green.
7. **MEMORY.** Update the project memory note (phase / next WP / test count).
8. **POST-WP AUDIT** (optional, when the user asks). A multi-finder audit — the just-shipped
   gate, cross-gate consistency, doc staleness, epistemic hygiene — yielding a *decisive*
   do-now-vs-defer recommendation. Usually one tight docs commit (± a small real fix); reject
   overbuild, defer backlog. Then the next WP.

## Durable invariants & gotchas

- **Environment.** Work from `~/Documents/Centaur` via the gitignored **`.venv`**
  (`.venv/bin/python`; PEP 668 — no system installs). Locally there is only `python3`; CI
  provides `python`. Cloud / remote launches must start from the repo dir (do **not** git-init
  the home dir).
- **One WP at a time.** Every commit leaves the tree green (relevant tests + a smoke path);
  size commits by blast radius, not line count. Don't begin the next WP automatically.
- **The user owns the calls.** Enum/vocabulary/scope/architecture decisions are surfaced as
  questions, not assumed.
- **Fail-closed, never falsely pass** (CONSTITUTION §3). A check that can't run (missing tool,
  zero inputs, unreadable/empty file, broken upstream) exits non-zero — a gate that "passes"
  on nothing is worse than no gate. `draft` is **STRUCTURAL ONLY** and must report active vs
  not-yet-implemented checks; its `[SKIP]` list shrinks as WPs land.
- **Synthetic fixtures, secret-scan-clean.** `factbase/`, `examples/`, and `tests/fixtures/`
  are all scanned. Keep deliberately-fake secrets only under the secret-scan fixture dir;
  unsafe safety fixtures are placeholder shapes with no real harmful content (a machine-checked
  invariant).
- **Concurrent sessions.** The user runs other scripts/sessions in this repo — do **not** run
  file-writing commands during a review, and stage explicit paths (not `git add -A`).
- **The reproducibility ledger is a lockfile (WP7).** Adding / editing / removing any
  declared input (`factbase/*.yaml`, `knowledge/**/*.yaml`, a scenario's `state/private/*.yaml`
  or root files) makes `examples/<name>/run_ledger.yaml` stale and CI fails with
  `hash-mismatch` / `extra-input` / `missing-input`. The fix (the failure prints it):
  `.venv/bin/python scripts/validate_run_ledger.py --write`, then commit `run_ledger.yaml`.
  Treat it like a step in the WP loop whenever a WP touches a declared input.
- **Attestations + the calibration / feasibility records pin the ledger too (WP8–9, WP-E2c).**
  `examples/<name>/review.yaml` + `signoff.yaml`, a WP9 `calibration.yaml` (only when
  `calibration_status: CALIBRATED`), and a WP-E2c `calibration_feasibility.yaml` (the honest "cannot
  calibrate this channel" record, under `UNCALIBRATED`) all record the ledger's `code_version`; when a
  declared-input change regenerates the ledger, they go **stale** (`stale-attestation` /
  `stale-calibration` / `stale-feasibility`, CI release fails). The same WP-loop step: after `--write`,
  update `code_version` in `review.yaml` + `signoff.yaml` (re-review / re-sign), any `calibration.yaml`
  (re-score / re-record), and any `calibration_feasibility.yaml` (re-assess) to match, and re-commit.
  None of these is itself a declared ledger input (the binding is one-directional). Approval, calibration,
  and feasibility bind to a reproducible snapshot, by design. (`ru_ua_salvo_heterogeneous` carries an
  UNCALIBRATED signoff + a `calibration_feasibility.yaml` verdict NOT_FEASIBLE; ukraine stays
  `ILLUSTRATIVE` with no record — the CALIBRATED calibration step only bites a scenario claiming it.)
  A feasibility record's blocked provenance hash (`sha256_status: BLOCKED_FETCH_AUTH_GATED`, `sha256:
  null`) upgrades to `PINNED` + a real 64-hex hash only when the source is actually fetched — never fabricate one.
- **Two environment traps seen in practice:** a **pending macOS update** can read-only-lock
  *existing* files on the data volume (write → `EPERM`; new files still create) — a reboot
  clears it; and the Bash tool's **cwd can go stale** after a long Workflow — `cd` from an
  absolute path before file ops.

## One-line checklist

`plan → research/design/red-team → decide → implement → verify → adversarial review →
atomic commit → CI green → ledger → memory → (audit) → next WP.`

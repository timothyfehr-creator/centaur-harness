# Progress Ledger

Cross-work-package status for the Centaur harness — one short entry per work
package. See [IMPLEMENTATION_PLAN_V2.md](../IMPLEMENTATION_PLAN_V2.md) for the
canonical plan and ordering.

## WP-1 — Bootstrap scaffold ✅ complete (commit `beb3daf`)

Created the smallest viable repo so verification could run: `scripts/verify.py`,
`tests/test_verify_modes.py`, `.github/workflows/ci.yml`, `.gitignore`,
`README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/CONSTITUTION.md`,
`docs/COMMAND_SAFETY.md`.

## WP0.1 — Scaffold verification & CI ✅ complete

WP0.1's behavior was already delivered by the WP-1 bootstrap; this pass hardened
the tests, added this ledger, and ran CI for real.

| Acceptance criterion | Status |
|---|---|
| `python scripts/verify.py --mode scaffold` exits 0 | ✅ |
| `python scripts/verify.py` exits 0, defaults to scaffold | ✅ |
| unknown modes exit nonzero with a clear error | ✅ (exit 2, `unknown mode`) |
| `pytest` exits 0 | ✅ (5 passed) |
| CI runs scaffold-verify + pytest | ✅ (see run below) |
| existing checks preserved | ✅ |

- Tests hardened in commit `d349421` (draft/release assert the clear `unknown
  mode` error; scaffold asserts its `scaffold verification OK` success message).
- **GitHub Actions:** ✅ success — run
  [27730539855](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27730539855)
  on `924d260` (steps *Scaffold verification* and *Tests* both passed).
- Note: the local machine has `python3` (3.14) but no `python` binary; tests
  invoke via `sys.executable`, and CI provisions `python` via
  `actions/setup-python`.

## WP0.2 — Command safety & secret scan ✅ complete

Implemented `scripts/secret_scan.py` (a minimum gate, not an oracle), wired it into
CI, and flipped the command-safety docs from deferred to implemented.

| Acceptance criterion | Status |
|---|---|
| bare `python scripts/secret_scan.py` exits 0 | ✅ (13 files; fail-closed if git fails / 0 files) |
| safe fixture exits 0 | ✅ |
| unsafe fixture exits 1 (fake secret caught) | ✅ (masked, names the file) |
| `pytest` exits 0 | ✅ (30 passed) |
| CI runs the secret scan | ✅ (step before scaffold + tests) |
| no broad framework / new dependency added | ✅ (pure stdlib) |

- Scanner + fixtures + tests: `eae1595`; CI wiring + docs + tracked fixtures:
  `553f98a`; hardening per adversarial review (fail-closed, delimited-token
  placeholders, per-rule recall, UUID precision): `cbbe2c8`.
- CI action versions bumped to `checkout@v5` / `setup-python@v6` (Node-20
  deprecation warning cleared).
- **GitHub Actions:** ✅ success — run
  [27731991363](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27731991363)
  on `cbbe2c8` (Secret scan, Scaffold verification, Tests all passed).
- Note: fixture/test secrets are synthetic and prefix-split so GitHub push
  protection does not block the push.

## WP1.1 — Enforceable scenario schema ✅ complete

Made scenario YAML machine-validatable (structural only; sourcing is WP2.3). Chose
**PyYAML + a hand-rolled validator** (one pinned dep) over jsonschema/pydantic — the
cross-field rules need custom code regardless.

| Acceptance criterion | Status |
|---|---|
| valid fixtures + the real example pass | ✅ |
| each invalid fixture fails for its EXACT reason | ✅ (9 codes, one finding each) |
| schema_version / branches / ≥3 signposts / ≥1 falsifier / rationale-or-update / prob sum | ✅ |
| scenario validation wired into scaffold | ✅ (structural; fails closed without PyYAML) |
| `pytest` exits 0 | ✅ (46 passed) |
| existing checks preserved; no out-of-scope work | ✅ |

- Feature commit `ea9973e`: `scripts/validate_schemas.py`,
  `examples/ukraine_crimea_logistics/scenario.yaml` (ILLUSTRATIVE/unsourced),
  `schemas/scenario.schema.md`, valid/invalid fixtures + `tests/test_schema_validation.py`,
  scaffold hook in `verify.py`, `requirements-dev.txt` (pytest + PyYAML), CI step.
- **GitHub Actions:** ✅ success — run
  [27733665200](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27733665200)
  on `ea9973e` (Install deps, Secret scan, Schema validation, Scaffold verification,
  Tests all passed).
- Deferred within WP1.1 (flagged): `label`/`as_of_date` enforcement (WP3.2 / §6);
  tighter probability tolerance (backlog); other schemas (WP1.2). PyYAML is now a
  required dependency — scaffold **fails closed** without it.

## Deferred (not started)

Core schema skeletons for agents/sources/claims/events/turns (WP1.2), source/claim
validation (WP2.x), safety enforcement & output labels (WP3.x), draft mode (WP4.1),
release mode (WP8.2), and engine work.

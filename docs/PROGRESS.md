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

## Deferred (not started)

Schemas (WP1.x), source/claim validation (WP2.x), safety enforcement & output
labels (WP3.x), draft mode (WP4.1), release mode (WP8.2), scenario content, and
engine work.

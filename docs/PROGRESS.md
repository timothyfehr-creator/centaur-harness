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
- **GitHub Actions:** _recorded after the first run — see the commit that records
  the CI result._
- Note: the local machine has `python3` (3.14) but no `python` binary; tests
  invoke via `sys.executable`, and CI provisions `python` via
  `actions/setup-python`.

## Deferred (not started)

Schemas (WP1.x), source/claim validation (WP2.x), safety enforcement & output
labels (WP3.x), draft mode (WP4.1), release mode (WP8.2), real secret scanner
(WP0.2 — `scripts/secret_scan.py`, currently documentation-only in
[docs/COMMAND_SAFETY.md](COMMAND_SAFETY.md)), scenario content, and engine work.

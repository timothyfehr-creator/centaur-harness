# Contributing

A short "start here" for working in this repo. The operating philosophy lives in
[docs/CONSTITUTION.md](docs/CONSTITUTION.md); the full delivery cadence is in
[AGENTS.md](AGENTS.md) and [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # pytest, PyYAML, ruff
```

Python 3.11+. Locally the interpreter is `python3` (there is no `python` binary); CI
provisions `python` via `actions/setup-python`.

## The loop

Every change follows the same fixed loop:

1. **Plan** one work package (small, single-purpose).
2. **Implement** it. Engine/state code is deterministic — no unseeded randomness, no
   unpinned external data, no magic numbers without a source.
3. **Green-gate** before committing:
   ```bash
   .venv/bin/python -m pytest -q                  # the full suite
   .venv/bin/python scripts/verify.py --mode release   # the composed gate
   .venv/bin/ruff check .                          # lint
   .venv/bin/python scripts/secret_scan.py <changed files>
   ```
   Each gate **fails closed**; a clean run is `exit 0`. A red gate stops the commit.
4. **Review** — substantive or epistemically-sensitive work (anything touching
   attestation or calibration) gets an adversarial review and is **human-gated**, with a
   genuinely independent (cross-vendor) pass before it is trusted. See
   [docs/RUNBOOK.md](docs/RUNBOOK.md).
5. **Commit** atomically — each commit leaves the tree green.

## The lockfile discipline

Each scenario's `run_ledger.yaml` pins a content hash of every declared input. If you
edit a declared input (`factbase/*`, `knowledge/**`, a scenario's `rules.yaml` /
`engine_state.yaml` / `state/*`), regenerate the ledger and re-pin the attestations:

```bash
.venv/bin/python scripts/validate_run_ledger.py examples/<scenario>/run_ledger.yaml --write
```

then update the `code_version` in that scenario's `review.yaml` / `signoff.yaml`, or CI
fails closed on the drift. The failure message prints the exact fix.

## Conventions

- `core/` is the deterministic engine; `scripts/` holds the gates + `verify.py`; tests
  import them via the `pythonpath` set in [`pyproject.toml`](pyproject.toml) (no
  per-file `sys.path` hacks).
- Lint config is in `pyproject.toml` (`ruff`); line length is advisory — long, dense
  design-rationale comments are intentional.
- Fixtures under `tests/fixtures/` intentionally contain fake secret-shaped strings and
  are kept out of the secret scan; never put a real secret anywhere.

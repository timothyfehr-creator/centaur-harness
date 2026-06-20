# Centaur Harness

A disciplined, verifiable development harness for centaur (human + AI) wargaming.
The near-term goal is **enforceable plumbing before engine**: minimum viable gates
that prevent unsourced, unsafe, malformed, unreviewed, or non-reproducible outputs
from appearing valid.

See **[IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md)** for the canonical plan
and **[docs/CONSTITUTION.md](docs/CONSTITUTION.md)** for the operating principles.

## Status

Phase 3 underway. Complete: repo-level `scaffold` verification and a secret scan
(Phase 0); the scenario + core schema layer (WP1.1–1.2); the full evidence chain —
source / claim / event validators and the source-or-label state gate (WP2.1–2.3); and
the §7 **safety gate** (WP3.1). Next: output-label validation (WP3.2) and draft mode
(WP4); release mode arrives later, in the plan's order. See
[docs/PROGRESS.md](docs/PROGRESS.md).

## Verification

```bash
python scripts/verify.py --mode scaffold   # repo-level integrity (+ structural scenario-schema check)
python scripts/secret_scan.py              # secret scan (a minimum gate)
python scripts/validate_schemas.py         # validate examples/**/scenario.yaml
python scripts/validate_sources.py         # source registry
python scripts/validate_claims.py          # claim→source resolution + source-tier rule
python scripts/validate_events.py          # event→claim resolution
python scripts/validate_state.py           # source-or-label state gate (CONSTITUTION §5)
python scripts/safety_check.py             # safety gate — actionable-harm content (§7)
pytest                                      # run the test suite
```

CI runs these as ordered steps (the resolution gates are dependency-ordered: claims
after sources, events/state after claims, safety after state). Each gate **fails
closed** (exit 0 clean / 1 findings / 2 usage-or-fail-closed).

`scaffold` mode checks repo-level integrity (required files/dirs present) and
**structurally** validates any `examples/**/scenario.yaml` that exist. It does
**not** require a scenario to exist, nor that its claims are sourced (sourcing is a
later phase) — only that a *present* scenario is well-formed.

Unknown modes — including the not-yet-implemented `draft` and `release` — exit
nonzero with a clear error, so the harness never falsely reports validity.

## Requirements

- Python 3.11+. On this machine the interpreter is `python3` (there is no `python`
  binary); use `python3 scripts/...` locally. CI provisions `python` via
  `actions/setup-python`, so the `python ...` commands above are correct in CI.
- Dependencies are declared in [`requirements-dev.txt`](requirements-dev.txt)
  (`pytest`, `PyYAML`). Install before running:

  ```bash
  python3 -m pip install -r requirements-dev.txt
  # On an externally-managed Python (PEP 668), use a venv:
  #   python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
  ```

- `PyYAML` backs the scenario-schema validator, which `scaffold` mode now invokes.
  Without it, scaffold **fails closed** with a clear error rather than skipping
  validation.

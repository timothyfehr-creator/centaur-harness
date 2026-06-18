# Centaur Harness

A disciplined, verifiable development harness for centaur (human + AI) wargaming.
The near-term goal is **enforceable plumbing before engine**: minimum viable gates
that prevent unsourced, unsafe, malformed, unreviewed, or non-reproducible outputs
from appearing valid.

See **[IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md)** for the canonical plan
and **[docs/CONSTITUTION.md](docs/CONSTITUTION.md)** for the operating principles.

## Status

Bootstrap scaffold (pre-WP0.1). Only repo-level `scaffold` verification exists.
Schemas, source/claim validation, safety checks, draft mode, and release mode are
**not** implemented yet — they arrive in later phases, in the plan's order.

## Verification

```bash
python scripts/verify.py --mode scaffold   # repo-level integrity check
python scripts/verify.py                    # defaults to --mode scaffold
pytest                                       # run the test suite
```

`scaffold` mode checks repo-level integrity only (required files/dirs present). It
does **not** require a sourced scenario, factbase, agent grounding, fog-of-war,
run ledger, review, signoff, or release artifacts.

Unknown modes — including the not-yet-implemented `draft` and `release` — exit
nonzero with a clear error, so the harness never falsely reports validity.

## Requirements

- Python 3.11+. On this machine the interpreter is `python3` (there is no `python`
  binary); use `python3 scripts/verify.py ...` locally. CI provisions `python` via
  `actions/setup-python`, so the `python ...` commands above are correct in CI.
- `pytest` for the test suite (`pip install "pytest>=8,<10"`).

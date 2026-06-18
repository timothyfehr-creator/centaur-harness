# Centaur Harness — Constitution

Short, durable principles. Mechanics live in the plan and the code; this file
states the commitments those mechanics must honor.

## 1. Gates before engine

Build enforceable verification before richer simulation. Do not build the
wargaming cathedral before the front door has a lock.

## 2. Smallest enforceable step

Each work package adds the smallest change that makes the repo safer or more
verifiable. No broad governance, ingestion, dashboards, or engine logic ahead of
its phase.

## 3. Honest status

Verification must never falsely pass.

- `scaffold` — repo-level integrity only.
- `draft` — structural validity; must report which checks are active versus not
  yet implemented, and must not imply analytical validity.
- `release` — unavailable or fails clearly until its gates exist.

## 4. World versus game

Real-world baselines and model/game outputs must be distinguishable. Outputs carry
explicit labels (for example `REAL_WORLD_BASELINE`, `ASSUMPTION`, `MODEL_OUTPUT`,
`GAMED_FUTURE`, `ANALYST_JUDGMENT`, `ILLUSTRATIVE`). Enforcement arrives in its
phase; the commitment holds from the start.

## 5. Evidence or label

A claim is either resolved to a source or explicitly labeled an assumption. Nothing
unsupported is silently treated as fact.

## 6. Reproducibility

Persisted run artifacts must be traceable: config/version, RNG seeds, as-of dates,
code version, and — for LLM-assisted steps — model name, model version, prompt
version, and temperature.

## 7. Safety scope

The harness supports strategic assessment, not actionable operational guidance.
Safety checks are a minimum gate, not a semantic oracle.

## 8. Evaluation is acceptance commands

Agent confidence is not evaluation. Passing a work package's acceptance commands is
the evaluation.

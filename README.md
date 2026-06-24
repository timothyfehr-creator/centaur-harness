# Centaur Harness

[![CI](https://github.com/timothyfehr-creator/centaur-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/timothyfehr-creator/centaur-harness/actions/workflows/ci.yml)

**A verifiable harness for centaur (human + AI) wargaming — it refuses to let a model's
output look more valid than it actually is.**

A *centaur wargame* is a strategic scenario played out by human and AI agents. The hard
part isn't running the game; it's **trusting the output** — knowing which claims are
sourced, which numbers are calibrated, which results are reproducible, and which are just
plausible-looking prose. This repo is the discipline layer that makes those distinctions
**enforceable**: a set of small, composable, **fail-closed gates** an output must pass to
be presented as valid. Anything unsourced, unsafe, malformed, unreviewed, uncalibrated, or
non-reproducible is *structurally flagged*, not quietly accepted.

The guiding stance is **honesty by construction** — the harness would rather block its own
output than over-claim:

- A clean release reports **`SELF-VERIFIED; NOT INDEPENDENTLY ATTESTED`**. It *cannot* spell
  "attested" unless a genuinely independent reviewer — allow-listed by a human — signed off;
  a model checking its own work is structurally unable to mark it approved.
- A model that can't be honestly calibrated **says so on the record** (`UNCALIBRATED`, plus a
  machine-checked "cannot calibrate this channel" finding) instead of dressing up illustrative
  numbers as validated ones.
- Every gate **fails closed**: if it can't evaluate something it errors (exit 2), never a
  silent pass.

## Quickstart

```bash
git clone https://github.com/timothyfehr-creator/centaur-harness && cd centaur-harness
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python scripts/verify.py --mode release   # the full composed gate
.venv/bin/pytest -q                                  # the test suite (~600 tests)
```

`verify.py` composes the individual gates into three modes — `scaffold` (repo integrity),
`draft` (the structural evidence/safety gates), and `release` (everything: reproducibility
+ attestation + calibration + the engine gates). It propagates the *worst* gate's exit code
(findings → 1, a gate that cannot run → 2), so it never falsely passes.

## What's inside

| Area | What it enforces |
|---|---|
| **Evidence chain** | every claim resolves to a source or carries an explicit label; events resolve to claims; state is source-or-label |
| **Safety + labels** | an actionable-harm content gate, and a required `world`-vs-`game` output label |
| **Reproducibility** | a per-scenario `run_ledger.yaml` lockfile pinning a content hash of every declared input; any drift fails CI |
| **Attestation** | per-scenario review + signoff, honest by construction (a self-check can't read as independent) |
| **Calibration** | `CALIBRATED` must resolve to a scored record; otherwise the model declares `UNCALIBRATED` / `ILLUSTRATIVE`, or records *why* a channel can't be calibrated |
| **Engine** | a deterministic, reproducible turn engine — typed state, a seeded RNG oracle, and replayable turn records (record-replay + recomputation + an idempotency hash) |

A dozen-plus gates, each also a standalone CI step; `verify.py` composes them. ~600 tests,
green in CI.

## Repository layout

- **`core/`** — the deterministic wargame engine: turn-record core, canonical serializer,
  seeded RNG oracle, combat resolvers, and the fog-of-war context compiler.
- **`scripts/`** — the gates (`validate_*.py`, `safety_check.py`, `secret_scan.py`) and
  `verify.py`, the composer.
- **`schemas/`** — the `*.schema.md` contracts each artifact must satisfy.
- **`examples/`** — illustrative scenarios with their engine runs, ledgers, and attestations.
- **`factbase/` · `knowledge/`** — the sourced evidence and agent knowledge books.
- **`tests/`** — ~600 tests. **`docs/`** — the design docs (start with the [Constitution](docs/CONSTITUTION.md)).

## Status & scope

The **enforceable-plumbing phase is complete** (the evidence, safety, reproducibility,
attestation, and calibration gates), and the **wargame engine is now in-repo and under active
build** — a deterministic salvo-combat resolver with replayable turn records. The most recent
work made the attestation honest by construction and was **independently reviewed (cross-vendor)**
over three adversarial rounds — which caught a real fail-open that four in-house review passes had
missed — ending in the harness's **first recorded INDEPENDENT attestation** (the het scenario; the
reviewer is allow-listed in [`attestation_reviewers.yaml`](attestation_reviewers.yaml)). The
repo-level banner stays conservative (`SELF-VERIFIED; NOT INDEPENDENTLY ATTESTED`) until *every*
scenario clears independent review.

**Everything here is `ILLUSTRATIVE` / `UNCALIBRATED` by design.** The models assert nothing
about the real world; the point of the project is the *discipline*, not a calibrated forecast.
Non-goals (for now): a full AI-vs-AI engine, multi-run orchestration, dashboards, and a
release-ready real-world scenario.

See [docs/PROGRESS.md](docs/PROGRESS.md) for the detailed build ledger and
[IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md) for the plan.

## How this was built

This repo is **AI-directed engineering under enforced discipline.** Every change follows a
fixed loop: plan → implement one work package → green-gate (the tests *and* the composed
verifier must pass) → an **adversarial review by independent agents** → atomic commit.
Epistemically-sensitive work — anything touching attestation or calibration — is
**human-gated** and put through a genuinely independent (cross-vendor) review before it is
trusted. The operating rules are written down, not improvised: [CONTRIBUTING.md](CONTRIBUTING.md)
(start here to build), [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md), the
[Constitution](docs/CONSTITUTION.md), and the delivery cadence in the [Runbook](docs/RUNBOOK.md).

## Documentation

- [docs/CONSTITUTION.md](docs/CONSTITUTION.md) — the operating principles the gates enforce.
- [docs/ENGINE_CONTRACT.md](docs/ENGINE_CONTRACT.md) — the engine's normative contract (determinism, replay, fog-of-war).
- [docs/RUNBOOK.md](docs/RUNBOOK.md) — the development cadence and the lockfile discipline.
- [docs/SAFETY_AND_SCOPE.md](docs/SAFETY_AND_SCOPE.md) — safety posture and scope boundaries.
- [docs/COMMAND_SAFETY.md](docs/COMMAND_SAFETY.md) — the safety gate's command/content policy.
- [docs/PROGRESS.md](docs/PROGRESS.md) — the build ledger (an internal working record; start here, in the README, for the overview).
- [schemas/](schemas/) — the per-artifact contract specs.

## Requirements

Python 3.11+ and the dependencies in [`requirements-dev.txt`](requirements-dev.txt)
(`pytest`, `PyYAML`, `ruff`). On an externally-managed Python (PEP 668), use a venv as in the
Quickstart. The `draft` and `release` modes require **git** (the safety gate scans tracked
files via `git ls-files`) — run inside the repository, not an export/tarball; without git
they fail closed by design. Locally the interpreter is `python3` (there is no `python`
binary); CI provisions `python` via `actions/setup-python`.

## License

[MIT](LICENSE) © 2026 Timothy Fehr.

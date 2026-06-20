# AGENTS.md

Operating rules for any agent (Claude Code, Codex, etc.) working in this repo.

Read **[IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md)** before changing code.

## Rules

1. Read the plan before changing code.
2. Implement only the named work package. Do not begin the next one automatically.
3. Explore first and write a short plan.
4. Preserve existing passing checks. Never weaken verification to make tests pass.
5. Add or update tests for every behavior change.
6. Run the exact acceptance commands for the work package.
7. Stop after two unsuccessful repair loops and report the blocker.
8. Report files changed, commands run, results, assumptions, and deferred work.

## Standard loop

```text
EXPLORE → PLAN → IMPLEMENT ONE WORK PACKAGE → RUN TARGETED TESTS →
RUN FULL ACCEPTANCE COMMANDS → SELF-REVIEW DIFF → REPORT → STOP →
INDEPENDENT SCOPE REVIEW → FIX ONLY BLOCKERS → COMMIT → NEXT WORK PACKAGE
```

## Anti-overbuild

Each work package implements the smallest enforceable improvement that makes the
repository safer or more verifiable. Do not add governance, ingestion pipelines,
dashboards, calibration frameworks, schemas, or engine logic ahead of their phase.
See the plan's "Anti-overbuild rule".

## Evaluation

Agent confidence is not an evaluation. Passing the work package's acceptance
commands is the evaluation. Every work package should include, where applicable, a
valid fixture, an invalid fixture, a regression test, and the exact acceptance
commands.

## Test fixtures & gates

- **Fixtures with secret-/credential-shaped content must be SYNTHETIC.** GitHub push
  protection (and our own `scripts/secret_scan.py`) will block or flag realistic or
  canonical provider keys (e.g. Stripe's documented example, AWS live keys). Use
  obviously-fake / test-mode values, and SPLIT provider prefixes via string
  concatenation (`"xoxb-" + "..."`) so the contiguous token never appears in committed
  source.
- Keep such samples under `tests/fixtures/` (and `tests/test_secret_scan.py`), which
  the secret scan excludes from the default/CI scan. Never place deliberately-fake
  secrets in other tracked files — they would fail the gate (or block the push).
- **Safety fixtures follow the same convention** (`scripts/safety_check.py`, the §7
  gate). Synthetic safe/unsafe content lives under `tests/fixtures/safety/` (excluded
  from the default scan, with the patterns file). Unsafe fixtures are placeholder text
  that trips a pattern with **no real harmful procedure** — a machine-checked invariant
  (`test_unsafe_fixtures_contain_no_concrete_procedure`). Use the `pragma: allowlist
  safety` marker to exempt a deliberately documented matching line. Operators can
  override the pattern file / enable the broader tier via the `CENTAUR_SAFETY_PATTERNS`
  env var. See [docs/SAFETY_AND_SCOPE.md](docs/SAFETY_AND_SCOPE.md).
- **Gates fail closed.** A check that cannot actually run (missing tool, zero inputs,
  unreadable file) must exit non-zero with a clear error — never silently report
  "OK". A gate that passes when it scanned nothing is worse than no gate. See
  [docs/CONSTITUTION.md](docs/CONSTITUTION.md) §3 (verification must never falsely
  pass).

## Dependencies

- Keep dependencies minimal — prefer the standard library. Add an external dependency
  only for a real need, pin it to a major range, and declare it in
  [`requirements-dev.txt`](requirements-dev.txt).
- Install locally in a virtualenv (the host Python is often externally managed,
  PEP 668): `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
- A gate that depends on a package must **fail closed** if the package is missing —
  exit non-zero with a clear message, never silently skip the check. (E.g. `scaffold`
  reports a problem when a scenario is present but PyYAML cannot be imported.)

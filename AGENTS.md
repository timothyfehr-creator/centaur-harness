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

# CLAUDE.md — Centaur Harness

Project guidance for Claude Code. This supplements the global principles and the
shared agent rules in [AGENTS.md](AGENTS.md). Read
[IMPLEMENTATION_PLAN_V2.md](IMPLEMENTATION_PLAN_V2.md) before editing.

## Mission anchor

- **Purpose:** produce a disciplined, verifiable harness whose gates prevent
  unsourced, unsafe, malformed, unreviewed, or non-reproducible outputs from
  appearing valid.
- **Primary artifact:** `scripts/verify.py` and the gates it composes — `scaffold`
  now (repo integrity + scenario schema). The schema, source, and **safety** gates
  ship as standalone CI steps today and get composed into `draft` (WP4); `release`
  later, in plan order.
- **Non-goals (for now):** a full AI-vs-AI wargame engine, institutional
  governance, multi-run orchestration, dashboards, calibration suites, OSINT
  ingestion, a release-ready scenario. See the plan's Non-goals.

## How to work here

- Build enforceable plumbing before engine logic (plan §3 sequencing).
- Implement one work package at a time; verify and review before the next.
- Keep `scaffold` mode repo-level and lightweight. Do not make it depend on a
  fully sourced scenario.
- `draft` and `release` modes are not implemented; they must fail clearly rather
  than falsely pass.

## Commands

```bash
python scripts/verify.py --mode scaffold   # repo-level integrity
python scripts/verify.py                    # defaults to scaffold
pytest                                       # test suite
```

(No `python` binary on the local machine — use `python3` locally; CI provides
`python`.)

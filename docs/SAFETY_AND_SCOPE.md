# Safety and scope — the §7 minimum gate

This document defines what `scripts/safety_check.py` (the **Safety check** CI step)
enforces and, just as importantly, what it does **not**. It is the executable form of
CONSTITUTION §7.

## CONSTITUTION §7 (verbatim)

> The harness supports strategic assessment, not actionable operational guidance.
> Safety checks are a minimum gate, not a semantic oracle.

## Purpose

A **defensive** content-safety gate: it detects and blocks **actionable operational
harm-instructions** so they cannot pass the pipeline. It is a pattern scanner — a
near-twin of `scripts/secret_scan.py` — over the repo's tracked files. It is **not** an
AI safety classifier and makes no judgement about analytic quality.

## Where the line sits

The gate distinguishes **strategic assessment** (which a wargaming harness must be free
to reason about) from **actionable operational how-to** (which it must not emit). Every
rule requires two co-occurring tokens on the **same physical line** — a harm/imperative
verb *and* a weapon/agent object — so ordinary strategic vocabulary never trips it.

| PASS — strategic assessment | BLOCK — actionable operational how-to |
|---|---|
| Force posture, unit sizes, logistics constraints | Weapon / CBRN / explosive construction or synthesis instructions |
| A modeled strike as a scenario event (e.g. "Ukraine strikes the bridge") | Explicit step-by-step procedures to acquire/assemble a weapon or harmful agent |
| Casualty-range outcome estimates | Optimizing a method for maximizing civilian casualties (a design objective) |
| Attrition rates, campaign-phase modeling | Sourcing guidance for a controlled weaponizable item |

## Tiers — choosing the line without touching code

`checks/safety_patterns.yaml` carries an `enabled_tiers` key:

- **`conservative`** (the default) — construction/synthesis instructions and explicit
  step-by-step mass-casualty how-to only. Does **not** flag strategic military
  discussion. This is the shipped line.
- **`broader`** — additionally flags operational targeting / strike-execution detail (a
  strike verb bound to precise coordinates, or prescriptive tactical phase sequencing
  against named assets). It carries a higher false-positive risk on legitimate scenario
  content (e.g. an analytic "Phase 1: suppress radar" phase description), so it is
  defined but **off by default**. Enable it by setting
  `enabled_tiers: [conservative, broader]`.

Operators can point the gate at an alternate pattern file with the
`CENTAUR_SAFETY_PATTERNS` environment variable (used to flip tiers in CI without
editing the checked-in YAML).

## Minimum-gate disclaimer (read this)

- It matches **regex signatures**, not meaning. It will miss obfuscated, paraphrased, or
  novel content.
- It is **line-local**: both trigger tokens must appear on one physical line.
  Newline-splitting them evades it.
- A clean scan means **"no obvious actionable harm-instruction"**, *not* "provably safe".
  Human judgement is still required.
- False negatives are an accepted cost of a minimum gate; false positives on strategic
  content are treated as bugs (the patterns are tightened, or a line is allowlisted).

## Running it / the allowlist marker

```bash
python scripts/safety_check.py            # scan tracked repo files (git ls-files)
python scripts/safety_check.py PATH ...   # scan the given files/dirs
```

A line containing the marker `pragma: allowlist safety` is skipped — the escape hatch
for a deliberately documented example. For instance, the following illustrative line
matches a pattern but is exempted so this document passes its own gate:

> BLOCK example — "synthesize the nerve agent …" (illustrative only)  <!-- pragma: allowlist safety -->

Exit codes: `0` clean · `1` unsafe match(es) found · `2` usage / fail-closed (the
patterns file is missing / empty / malformed, an unknown tier is configured, no rules
are enabled, or a default scan matches zero files).

## Out of scope (deferred)

- A semantic / ML AI-safety classifier, an exhaustive policy engine, a human
  legal-review workflow (out of scope for the harness).
- **Output-label / world-vs-game enforcement** — that is **WP3.2** (it reuses
  `WORLD_VS_GAME_LABELS`).
- **Draft-mode invocation** — wiring the safety gate into `verify.py --mode draft` is
  **WP4**. WP3.1 ships the gate as a standalone CI step only.

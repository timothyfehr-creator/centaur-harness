# Scenario schema (v1) — structural contract

Human-readable contract for `examples/**/scenario.yaml`. The **authoritative
enforcement** is [`scripts/validate_schemas.py`](../scripts/validate_schemas.py)
(hand-rolled, PyYAML `safe_load`); this file documents what it checks. WP1.1 is
**structural only** — it does not check that claims are source-backed (that is WP2.3).

## Top level

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | **yes** | string | non-empty |
| `branches` | **yes** | list | **≥ 2** items |
| `title` | no | string | — |
| `description` | no | string | — |
| `label` | no (this WP) | string | world-vs-game label; **enforced in WP3.2**, not here |
| `as_of_date` | no (this WP) | string | as-of date; **enforced later** (Constitution §6) |

## Per branch

| Field | Required | Type | Rule |
|---|---|---|---|
| `probability` | **yes** | number | a real number (not bool/str), `0 ≤ p ≤ 1` |
| `signposts` | **yes** | list | **≥ 3** non-empty items (leading indicators the branch is materializing) |
| `falsifiers` | **yes** | list | **≥ 1** non-empty item (observations that would disconfirm the branch) |
| `rationale` **or** `update_mechanism` | **yes** | string | at least one present and non-empty |
| `id`, `title`, `description` | no | string | — |

A signpost/falsifier item may be a plain string **or** a mapping with a non-empty
`description` (richer per-item fields are accepted but not required in WP1.1).

## Cross-field

- Branch probabilities must **sum within ±0.05 of 1.0** (`PROB_SUM_TOLERANCE`; loose by
  design, tightening is backlog).
- **No implicit residual**: branches are treated as mutually exclusive and exhaustive —
  a leftover probability mass must be its own explicit branch, not an implied remainder.

## Error codes

Structural codes — one invalid fixture each:
`missing-schema-version`, `missing-branches`, `probability-not-numeric`,
`probability-out-of-range`, `probability-sum-out-of-range`, `too-few-signposts`,
`missing-falsifier`, `missing-rationale-or-update`.

`yaml-parse-error` covers the non-structural failure paths — an unreadable file, a
YAML syntax error, or a top level that isn't a mapping (e.g. empty / a list). A
malformed fixture exercises the syntax-error branch.

## Limitations (this is a structural minimum gate)

- The ±0.05 sum tolerance is the only mutual-exclusivity/exhaustiveness check; "no
  implicit residual" is enforced *via* that tolerance, not a separate residual rule.
- Duplicate YAML keys follow PyYAML's last-wins semantics (not rejected).
- Sourcing and world-vs-game label enforcement are **not** checked here (WP2.3 / WP3.2).

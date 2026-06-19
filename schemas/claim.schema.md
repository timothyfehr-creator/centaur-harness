# Claim schema (skeleton, v1) — structural contract

Human-readable contract for a claim document (`claims.yaml`). Authoritative
enforcement is [`scripts/validate_schemas.py`](../scripts/validate_schemas.py)
(`--kind claim`). **Skeleton only** — structural shape, no source resolution
(claim-to-source resolution is WP2.1).

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `id` | yes | string | non-empty |
| `text` | yes | string | non-empty |
| `confidence` | yes | enum | one of the values below |

## `confidence` enum (PROVISIONAL)

`CONFIRMED`, `LIKELY`, `UNCERTAIN`, `UNASSESSED` — an intel-style **evidential status**
vocabulary. `UNASSESSED` is a tag for not-yet-sourced claims. Values are provisional
and may be refined. The top value, `CONFIRMED`, triggers the WP2.1 source-tier rule
(see below).

## Error codes

`missing-schema-version`, `missing-field` (names the field), `invalid-enum`
(field + allowed + got), `yaml-parse-error`.

## Limitations

This contract covers the **standalone** claim skeleton (`--kind claim`): structural
shape only. Claim→source **resolution** and the **tier rule** (a `CONFIRMED` claim
needs ≥1 non-`SOCIAL` source) are enforced at the **registry** level (WP2.1) by
[`scripts/validate_claims.py`](../scripts/validate_claims.py) over `factbase/claims.yaml`
+ `factbase/sources.yaml`, not by the standalone skeleton. Stale-claim decay and OSINT
ingestion are later WPs.

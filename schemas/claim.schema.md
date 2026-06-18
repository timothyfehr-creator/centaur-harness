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

`HIGH`, `MODERATE`, `LOW`, `UNASSESSED`. **Label vocabulary only**, borrowed from
ICD-203 analytic-confidence standards and Sherman Kent's Words of Estimative
Probability; the semantics (numeric ranges, source-tier cross-validation) are
**deferred to WP2.1**. `UNASSESSED` is a scaffold-stage tag for not-yet-sourced
claims. Values are provisional and may be refined.

## Error codes

`missing-schema-version`, `missing-field` (names the field), `invalid-enum`
(field + allowed + got), `yaml-parse-error`.

## Limitations

Skeleton only: no `source` references, no claim-to-source resolution, no tier↔
confidence cross-rules. Those arrive in WP2.1+.

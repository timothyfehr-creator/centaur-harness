# Source schema (skeleton, v1) — structural contract

Human-readable contract for a source document (`sources.yaml`). Authoritative
enforcement is [`scripts/validate_schemas.py`](../scripts/validate_schemas.py)
(`--kind source`). **Skeleton only** — structural shape, no resolution semantics
(claim-to-source resolution is WP2.1).

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `id` | yes | string | non-empty |
| `title` | yes | string | non-empty |
| `tier` | yes | enum | one of the values below |

## `tier` enum (PROVISIONAL)

`OFFICIAL`, `MAINSTREAM`, `SOCIAL`. **Label vocabulary only**, borrowed from the NATO
source-reliability scale (STANAG 2511) and OSINT tiering; the semantics (e.g. a
`CONFIRMED` claim may not rest solely on `SOCIAL` sources) are **deferred to WP2.1**.
Values are provisional and may be refined.

## Error codes

`missing-schema-version`, `missing-field` (names the field), `invalid-enum`
(field + allowed + got), `yaml-parse-error`.

## Limitations

Skeleton only: no claim-to-source resolution, no stale-date decay, no source-conflict
adjudication. Those arrive in WP2.1+.

# Event schema (skeleton, v1) — structural contract

Human-readable contract for an event document (`events.yaml`). Authoritative
enforcement is [`scripts/validate_schemas.py`](../scripts/validate_schemas.py)
(`--kind event`). **Skeleton only** — structural shape, no event semantics
(causality, claim links) which are WP2.2.

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `id` | yes | string | non-empty |
| `description` | yes | string | non-empty |
| `category` | yes | enum | one of the values below |

## `category` enum (PROVISIONAL)

`DIPLOMATIC`, `INFORMATION`, `MILITARY`, `ECONOMIC`. **Label vocabulary only**,
borrowed from the DIME framework; a skeleton records exactly one primary category.
Multi-tag support and causality edges are **deferred to WP2.2**. Values are
provisional and may be refined.

## Error codes

`missing-schema-version`, `missing-field` (names the field), `invalid-enum`
(field + allowed + got), `yaml-parse-error`.

## Limitations

Skeleton only: one primary category, no claim references, no actor/target links, no
causality. Those arrive in WP2.2+.

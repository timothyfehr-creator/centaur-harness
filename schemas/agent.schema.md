# Agent schema (skeleton, v1) — structural contract

Human-readable contract for an agent document (`agents.yaml`). Authoritative
enforcement is [`scripts/validate_schemas.py`](../scripts/validate_schemas.py)
(`--kind agent`). **Skeleton only** — structural shape, no grounding or behaviour
(agent grounding is WP5).

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `id` | yes | string | non-empty |
| `name` | yes | string | non-empty |
| `type` | yes | enum | one of the values below |

## `type` enum (PROVISIONAL)

`STATE`, `INSTITUTION`, `NON_STATE`. **Label vocabulary only**, borrowed from
international-relations actor typology; the semantics (capabilities, fog-of-war
filters) are **deferred to WP5/WP6**. Values are provisional and may be refined.

## Error codes

`missing-schema-version`, `missing-field` (names the field), `invalid-enum`
(field + allowed + got), `yaml-parse-error`.

## Limitations

Skeleton only: no knowledge-book references, no capability/behaviour modelling, and
no cross-document links. Those arrive in WP5+.

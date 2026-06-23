# Turn schema (skeleton, v1) — structural contract

> **Superseded for the engine.** This is the early *skeleton* turn document. The wargame
> engine's durable, replayable turn record is the richer **[turn_record.schema.md](turn_record.schema.md)**
> (ordering, idempotency, and replay semantics shipped with it in WP-E1). This skeleton is kept
> as the structural `--kind turn` contract; its "deferred" notes below refer to that skeleton, not
> the engine's turn record.

Human-readable contract for a turn document (`turns.yaml`). Authoritative enforcement
is [`scripts/validate_schemas.py`](../scripts/validate_schemas.py) (`--kind turn`).
**Skeleton only** — structural shape, no ordering or replay semantics on this kind.

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `id` | yes | string | non-empty |
| `number` | yes | integer | must be an integer (a bool is rejected) |

## Provenance (PROVISIONAL)

A turn is a discrete timestep, per conventional tabletop-wargame structure. WP1.2
enforces only that `number` is an **integer** — uniqueness, ordering, and replay are
**deferred to WP7**.

## Error codes

`missing-schema-version`, `missing-field` (names the field), `wrong-type`
(field + expected type), `yaml-parse-error`.

## Limitations

Skeleton only: no ordering/uniqueness constraint on `number`, no run/turn state, no
replay. Those arrive in WP7.

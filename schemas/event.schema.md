# Event schema (skeleton, v1) — structural contract

Human-readable contract for an event document (`events.yaml`). The standalone
structural shape is enforced by
[`scripts/validate_schemas.py`](../scripts/validate_schemas.py) (`--kind event`);
event→claim **resolution** is enforced at the registry level (WP2.2) by
[`scripts/validate_events.py`](../scripts/validate_events.py).

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `id` | yes | string | non-empty |
| `description` | yes | string | non-empty |
| `category` | yes | enum | one of the values below |
| `confidence` | yes | enum | one of the values below |

## `category` enum (PROVISIONAL)

`DIPLOMATIC`, `INFORMATION`, `MILITARY`, `ECONOMIC`. **Label vocabulary only**,
borrowed from the DIME framework; a skeleton records exactly one primary category.
Multi-tag support and causality edges are deferred. Values are provisional.

## `confidence` enum (PROVISIONAL)

`CONFIRMED`, `LIKELY`, `UNCERTAIN`, `UNASSESSED` — **reuses the claim evidential-status
vocabulary** ([claim.schema.md](claim.schema.md)). Values are provisional.

## Registry: event→claim resolution (WP2.2)

In an event **registry** (`factbase/events.yaml`), each event additionally carries a
`claims` list referencing claim ids in `factbase/claims.yaml`. `validate_events.py`
requires **≥1 claim ref per event** (independent of confidence) and that every ref
resolves. Error codes there: `missing-claim-ref`, `unresolved-claim-ref`,
`duplicate-id`, plus the skeleton codes.

## Error codes (skeleton)

`missing-schema-version`, `missing-field` (names the field), `invalid-enum`
(field + allowed + got), `yaml-parse-error`.

## Limitations

No event causality, actor/target links, multi-tag categories, or stale decay. A
**confidence-consistency** rule (event vs cited claims) is intentionally **not**
enforced. The ≥1-claim-ref invariant is a likely future-relaxation point for raw /
unsourced events.

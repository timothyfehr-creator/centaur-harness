# Assumptions schema (v1) — analytical-hypothesis registry

Contract for `factbase/assumptions.yaml`. Validated (folded) by
[`scripts/validate_agents.py`](../scripts/validate_agents.py) — it is the resolution target
for agent capability/behavioral refs, so it has no standalone gate.

## Registry shape

```yaml
schema_version: "1.0"
assumptions:
  - {id, statement}
```

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty (registry level) |
| `assumptions` | yes | list | non-empty (empty ⇒ fail-closed exit 2) |
| `id` | yes | string | non-empty; unique within the registry |
| `statement` | yes | string | non-empty |

## Why no `label` / `confidence` / `sources`

An entry here **is**, by construction, a CONSTITUTION §4 `ASSUMPTION` — the registry is
**mono-label by location**, so it needs no per-entry `label`. (A *state* item can carry any
of the six `WORLD_VS_GAME_LABELS`, so it needs the discriminator; an assumption does not.)
Assumptions are **asserted, not source-backed** — that is exactly what distinguishes them
from claims — so there is no `confidence` or `sources` field. An agent grounds a capability
in an assumption when no claim backs it; behavioral assumptions resolve to assumption ids
**only**.

## Error codes

`missing-field` (id/statement, tagged `assumptions[i]`), `duplicate-id`. A malformed entry
in an otherwise-usable registry is a finding (exit 1); a missing / empty / non-mapping
registry is fail-closed (exit 2). All shipped entries are SYNTHETIC / ILLUSTRATIVE.

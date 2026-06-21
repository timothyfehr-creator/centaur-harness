# Agent schema (v1) — grounding contract

Contract for an agent **registry** (`agents.yaml`). Authoritative enforcement is
[`scripts/validate_agents.py`](../scripts/validate_agents.py) (a CI step and a `draft`-mode
gate). WP5 adds the **grounding** layer on top of the WP1.2 structural skeleton: agents must
reference compact knowledge books and resolve their capability/behavioral claims to the
factbase, so they are grounded rather than generic chatbots.

> **Two validators, two shapes.** `validate_schemas.py --kind agent` validates a *single*
> agent **skeleton** doc (`{schema_version, id, name, type}`) — used only by the schema
> fixtures. `validate_agents.py` owns the **registry** (`{schema_version, agents: [...]}`)
> and the grounding rules below. (Running `validate_schemas.py agents.yaml` with no `--kind`
> would mis-validate the registry as a single doc — don't; that footgun is harmless because
> nothing in CI/scaffold does it.)

## Registry shape

```yaml
schema_version: "1.0"
agents:
  - {id, name, type, knowledge: [...], capabilities: [{statement, refs: [...]}], behavioral_assumptions: [...]?}
```

## Agent fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `id` | yes | string | non-empty; unique within the registry |
| `name` | yes | string | non-empty |
| `type` | yes | enum | `STATE` / `INSTITUTION` / `NON_STATE` (IR actor typology, provisional) |
| `knowledge` | grounding | list[string] | book-ids; every id resolves to the `knowledge/` catalog; ≥1 *resolving* book is grounding leg 1 |
| `capabilities` | grounding | list[{statement, refs}] | each `statement` non-empty; each `refs` id resolves to a **claim or assumption**; ≥1 capability with a resolving ref is grounding leg 2 |
| `behavioral_assumptions` | no | list[string] | resolve-if-present, to **assumption** ids only (claims do not satisfy these) |

## The grounding bar (CONSTITUTION §4/§5)

An agent is **`ungrounded-agent`** if it has **no resolving knowledge book** OR **no
capability with at least one resolving claim/assumption ref**. Citing a book alone is not
enough — the capability leg is what ties the agent to the factbase, so a "generic chatbot
wearing a citation" fails. Capability refs resolve to the **union** of claim ids
(`factbase/claims.yaml`) and assumption ids (`factbase/assumptions.yaml`).

## Error codes

`missing-schema-version`, `missing-field` (id/name, or a capability `statement`),
`invalid-enum` (type), `duplicate-id`, `unresolved-knowledge-ref`,
`unresolved-capability-ref`, `unresolved-assumption-ref`, `ungrounded-agent`. Fail-closed
(exit 2) if the agents registry, claims, assumptions, or the knowledge index is missing /
unreadable / empty / non-mapping (resolution can't be judged). One consolidated finding per
agent per ref-kind.

## Limitations / deferred

Resolution-only: knowledge books are compact catalogs (see
[`knowledge_book.schema.md`](knowledge_book.schema.md)), not encyclopedias; their content is
not gated. No numeric capability modeling, no doctrine libraries, no retrieval, no
fog-of-war filters (WP6). Assumptions are validated (folded) here — see
[`assumptions.schema.md`](assumptions.schema.md).

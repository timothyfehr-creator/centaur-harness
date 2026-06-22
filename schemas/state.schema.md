# State schema (v1) — the source-or-label gate

Contract for a scenario **state registry** (e.g.
`examples/<name>/initial_state.yaml`). Enforced by
[`scripts/validate_state.py`](../scripts/validate_state.py) (a CI step), which resolves
state items against `factbase/claims.yaml`. State is **registry-only** — there is no
standalone `--kind state` document.

## Registry shape

```yaml
schema_version: "1.0"
as_of_date: "YYYY-MM-DD"     # optional, accepted-but-unvalidated (a later WP)
items:
  - {id, statement, label, claims: [claim-id, ...]?}
```

## Item fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `id` | yes | string | non-empty; unique within the registry |
| `statement` | yes | string | non-empty |
| `label` | yes | enum | a world-vs-game label (below) |
| `claims` | conditional | list | required iff `label` is `REAL_WORLD_BASELINE`; any present refs must resolve |

## `label` enum — CONSTITUTION §4 world-vs-game labels

`REAL_WORLD_BASELINE`, `ASSUMPTION`, `MODEL_OUTPUT`, `GAMED_FUTURE`, `ANALYST_JUDGMENT`,
`ILLUSTRATIVE`. Shared constant `WORLD_VS_GAME_LABELS` in `validate_schemas.py` (reused by
the WP3.2 output-label gate). `REAL_WORLD_BASELINE` is the **only** label that asserts an
external real-world fact.

## The source-or-label rule (CONSTITUTION §5)

- A `REAL_WORLD_BASELINE` item must cite **≥1 claim** that resolves to the claim registry,
  or be relabeled to any non-`REAL_WORLD_BASELINE` label → else `unsupported-baseline`.
- Any item that carries `claims` must have **every** reference resolve → else
  `unresolved-claim-ref` (consolidated to one finding per item).
- Items not labeled `REAL_WORLD_BASELINE` need no claims.

Error codes: `missing-schema-version`, `missing-field`, `invalid-enum`, `duplicate-id`,
`unsupported-baseline`, `unresolved-claim-ref`. Fail-closed (exit 2) on a missing / empty /
non-mapping state or claims registry (an empty `items:` list is a refusal, not a pass).

## Fog-of-war partition (WP6)

A scenario may also carry a **fog-of-war partition** — the same v1 state registry above, split
by *visibility* across files (no new fields, no schema-version bump):

```
examples/<scenario>/state/
  public.yaml                 # visible to ALL agents + the adjudicator
  private/<agent-id>.yaml     # visible to that agent + the adjudicator only
  private/adjudicator.yaml    # visible to the adjudicator only — never any agent
```

**Visibility is the file location** — there is no per-item `visible_to` field.
[`core/context_compiler.py`](../core/context_compiler.py) compiles, for one agent, the registry
it may see (public items + its own private items; the adjudicator sees public + every private
file). `examples/.../initial_state.yaml` is a **separate** WP2.3 artifact and is **not** part of
the partition.

**Invariants (fail-closed — `FogError`):** each `private/<id>.yaml` filename must be a real
`agents.yaml` id or the reserved id `adjudicator` (no orphan/unowned private file); **no agent
may be named `adjudicator`** (it would see everything); item ids are **globally unique** across
public ∪ all private files (no shadowing); all partition files share one `schema_version`; an
empty `items:` is a refusal. The compiled context is itself a valid state registry (it passes
`validate_state`), takes the public `as_of_date`, and is **deterministic** (public-first then the
agent's private, input order; no RNG/clock; inputs never mutated).

**Adjudicator visibility is explicit** — an enumerated "sees all" branch plus a real
`adjudicator.yaml`, not an absence-of-rule default. The compiler is a **library** proven by
`tests/test_context_compiler.py` (positive + negative leak + fail-closed), **not** a `draft`
gate. **Deferred:** active deception, delayed intelligence, stale BDA, probabilistic sensing —
hence no per-item visibility field and no turn-gated reveal in WP6.

## Limitations

State→claim is a **resolution** check only — a claim's own confidence/source-tier discipline
is enforced upstream by [`validate_claims.py`](../scripts/validate_claims.py). This relies on
**CI ordering**: `validate_claims` runs before `validate_state` (both default to
`factbase/claims.yaml`), so a resolvable claim has already passed the tier gate; running
`validate_state` standalone against an unvalidated claims file would not re-check it. No numeric
state scales, no state mutation, no confidence field on state items (claim confidence lives
on the claims). General draft-artifact label enforcement is WP3.2.

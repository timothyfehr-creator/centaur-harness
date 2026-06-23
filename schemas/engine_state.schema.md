# Engine state schema (v1) — the typed compute authority

Contract for the engine's **typed canonical state** (`state/engine/public.yaml` and
`state/engine/private/adjudicator.yaml` under a scenario). This is the **compute surface** the
resolver reads and `reduce()` writes — distinct from, and **in addition to**, the prose
[state registry](state.schema.md), which stays the *evidence ledger* (free-text `statement` + a
world-vs-game `label`, no numeric slot). **Enforced** by
[`scripts/validate_engine_state.py`](../scripts/validate_engine_state.py) (structural + digest-scope; a
`release`-tier gate) with golden-vector tests. See [docs/ENGINE_CONTRACT.md](../docs/ENGINE_CONTRACT.md)
for the digest, canon, and partition rules referenced below.

## Document shape (an envelope)

```yaml
schema_version: "1.0"
state:                                  # the hashed payload (see state_digest)
  as_of_turn: 0                         # integer; the turn this state is the head of
  entities:
    - id: blue_supply                   # globally unique within this partition file
      type: FORCE                       # FORCE | ROUTE | ROUTE_SECRET | SINK | STRIKE_FORCE | AIR_DEFENSE
      fields:
        origin:     {value: 100, unit: units}
        in_transit: {value: 0,   unit: units}
        delivered:  {value: 0,   unit: units}
        loss_sink:  {value: 0,   unit: units}
state_digest:                           # computed over the `state` field ONLY (excludes itself)
  algorithm: sha256
  domain: canonical                     # engine canon-v1 (normalizing), NOT the ledger content-raw domain
  value: "<64 hex>"
```

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `state` | yes | mapping | the hashed payload; contains `as_of_turn` + `entities` |
| `state.as_of_turn` | yes | integer | ≥ 0; a bool is rejected |
| `state.entities` | yes | list | ≥ 1 entity; `id` globally unique across the partition (below) |
| `state_digest` | when sealed | mapping | typed digest `{algorithm, domain, value}`; **`value` is computed over the `state` field only** (self-reference excluded). A *bare scenario-input* envelope MAY omit it — `turn_record.assemble()` seals the state with the digest; the validator enforces digest-scope only when it is present |

### Entity fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `id` | yes | string | non-empty; globally unique across `public` ∪ all `private` typed files |
| `type` | yes | enum | `FORCE` \| `ROUTE` \| `ROUTE_SECRET` \| `SINK` \| `STRIKE_FORCE` \| `AIR_DEFENSE` (the last two are the WP-E2a additive extension — ADJUDICATION_LEDGER ECI-2, backward-compatible, no `schema_version` bump) |
| `fields` | yes | mapping | name → `{value, unit}`; `value` is `number`/`string`/`bool`; `unit` a non-empty string |

## Fog-of-war partition (sibling of the prose compiler)

The typed state is partitioned by **file = visibility**, exactly like the prose registry, and is
projected by a *sibling* typed-state projector that **reuses
[`core/context_compiler.py`](../core/context_compiler.py)'s `load_partition` invariants** (owner =
filename stem, no agent named `adjudicator`, **globally-unique ids**, single `schema_version`). The
prose compiler is **unchanged** — typed state has a different shape, so it gets its own projector.

```
state/engine/
  public.yaml                 # blue_supply, route:r1, route:r2  — visible to all agents + adjudicator
  private/adjudicator.yaml    # route_secret:r1 (block_threshold) — adjudicator only, never any agent
```

**C3 hidden-property rule:** a public entity with one hidden property is modelled as **two entities**
with distinct ids — public `route:r1` (in `public.yaml`) and a separate adjudicator-owned
`route_secret:r1` (in `private/adjudicator.yaml`) that references the public route by a plain
`subject_route` field. This preserves global-id-uniqueness with **no cross-file id collision and no
field-level merge**. The hidden numeric `block_threshold` therefore never appears in any agent's
projection (the existing no-leak test covers it).

## Slice entities (contested_logistics_abstract)

`blue_supply` (FORCE: `origin`/`in_transit`/`delivered`/`loss_sink`, units), `route:r1` (ROUTE:
`capacity`, `blockable: true`), `route:r2` (ROUTE: `capacity`, `blockable: false`), `route_secret:r1`
(ROUTE_SECRET: `subject_route: "r1"`, `block_threshold` int 0–99, adjudicator-only). **Conservation
invariant:** `origin + in_transit + delivered + loss_sink` is constant (= 100) across every turn.

## Slice entities (ru_ua_salvo_homogeneous / ru_ua_salvo_heterogeneous)

The salvo scenarios use `STRIKE_FORCE` (strike pools) + `AIR_DEFENSE` (interceptor pools). **Homogeneous
(WP-E2a):** one `russia_strikeforce` + one `ukraine_air_defense`. **Heterogeneous (WP-E2b1):** one
`STRIKE_FORCE` per threat class (`russia_strike_{drone,cruise,ballistic}`), one `AIR_DEFENSE` per
interceptor type (`ukraine_intc_{short,long,pac3}`), plus a network-aggregate `AIR_DEFENSE`
(`ukraine_air_defense`) carrying `cumulative_intercepted`, `lethality_collapse_streak`,
`lethality_collapsed`, `magazine_non_depleting`, `magazine_weeks_remaining`, `culminated` (additive
fields — no `schema_version` bump). All ASSUMED / UNCALIBRATED.

## Error codes (`validate_engine_state.py` emits)

`missing-schema-version`, `missing-field`, `wrong-type`, `invalid-enum` (bad entity `type`),
`duplicate-id` (across the partition), `digest-scope-violation` (`state_digest` not computed over the
`state` field only), `non-negative-violation` / `conservation-violation` (checked by `reduce()` on the
resulting state, not at rest).

## Limitations / deferred

Per-field epistemic labels (an entity field
carrying both `ASSUMED` and `MODEL_OUTPUT`) are **deferred**: the slice mixes labels only at the
*entity/item* grain (handled by the prose registry's `label`), so the bounded subject-keyed-field model
is not built. Multi-turn `in_transit` carrying across turns, multiple dispatches, and branching are out
of scope.

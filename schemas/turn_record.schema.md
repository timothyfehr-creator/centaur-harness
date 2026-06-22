# Turn record schema (v1) — the single durable authority

Contract for a **turn record** — the engine's keystone. It is the **one durable byte object** that
constitutes a committed turn: the typed [engine state](engine_state.schema.md), the validated
[command batch](engine_command.schema.md), the ordered [transition events](transition_event.schema.md),
the draw records, and the resulting state. **`engine_state` caches, every agent projection, and all
three replay tiers are DERIVED from this object alone, consulting no other authority.** **No validator
yet** — WP-E0 freezes this contract; `validate_turn_record.py` / the turn-replay gate + golden vectors
arrive in WP-E1. See [docs/ENGINE_CONTRACT.md](../docs/ENGINE_CONTRACT.md) for the phase order,
idempotency key, durability sequence, and projection policy.

> **Not the skeleton [`turn`](turn.schema.md).** `turn.schema.md` is the structural `turns.yaml`
> skeleton (`{id, number}`). A *turn record* is a different, richer kind with its own validator — they
> must not be conflated.

## Document shape (`run_record.turns` is a LIST; WP-E1 populates exactly one)

```yaml
schema_version: "1.0"
turn: 0
transition_input_hash: "<64 hex>"     # the idempotency key (candidate_id)
start_state: { ...engine_state... }    # the head this turn was resolved against
ruleset_version: "1"
resolver_id: contested_logistics
resolver_version: "1"
rng:                                   # null when no draw was consumed (PASS#8: no decorative seed)
  master_seed: 0
  algorithm: sha256-counter
  algorithm_version: "1"
  address_spec_version: "1"
  rng_namespace: root
  ordered_draw_addresses: [ ... ]
command_batch: [ ...sorted commands... ]
event_batch:   [ ...ordered events... ]
draw_records:
  - {draw_id: draw-001, address: {...}, raw_uint: 0, d100: 0, consuming_rule_id: block-resolve}
resulting_state: { ...engine_state... }   # == reduce(start_state, event_batch)
digests:
  start_state:     {algorithm: sha256, domain: canonical, value: "<hex>"}
  command_batch:   {algorithm: sha256, domain: canonical, value: "<hex>"}
  event_batch:     {algorithm: sha256, domain: canonical, value: "<hex>"}
  resulting_state: {algorithm: sha256, domain: canonical, value: "<hex>"}
runtime_fingerprint:
  engine_source_hash: "<git commit>(+dirty?)"
  python: "CPython 3.x.y"
  pyyaml_version: "x.y"
  serializer_version: "1"
  persistence_profile: local-posix-fs-v1
successor_slot: "run/turns/0001.json"     # the single-successor slot (distinct from transition_input_hash)
```

## Fields (authority + identity)

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `turn` | yes | integer | ≥ 0 |
| `transition_input_hash` | yes | string | `engine_canonical_digest` over {`start_state`, sorted `command_batch`, `ruleset_version`, `resolver_id`+version, `rng` request **or null**, all `schema_version`s, `canon_version`}. **The idempotency key.** `rng` is null when no draw → a no-draw turn is seed-independent. |
| `start_state` / `resulting_state` | yes | engine_state | `resulting_state == reduce(start_state, event_batch)` (PASS#9) |
| `rng` | conditional | mapping \| null | **null** unless a draw was consumed |
| `command_batch` | yes | list | canonically **sorted** (unordered set) |
| `event_batch` | yes | list | **ordered** (preserved) |
| `draw_records` | conditional | list | one per consumed draw; each carries address + `raw_uint` + `d100` + `consuming_rule_id` |
| `digests` | yes | mapping | typed `{algorithm, domain, value}` per part; **domain `canonical`** (engine), distinct from the ledger's `content-raw` |
| `runtime_fingerprint` | yes | mapping | compact: source hash + python + pyyaml + serializer + persistence_profile |
| `successor_slot` | yes | string | the run-local slot path enforcing one successor per head |

## Identity, commit & derivation (see [ENGINE_CONTRACT.md](../docs/ENGINE_CONTRACT.md))

- **Two identities:** `transition_input_hash` (idempotency — same inputs ⇒ same candidate) vs
  `successor_slot` (single successor per head, enforced by `O_EXCL` create, **not** `os.replace`).
  Slot empty → commit; same candidate + byte-identical → idempotent success; different candidate →
  `successor-exists` (PASS#10).
- **Sole authority:** the committed record is the truth; `engine_state.yaml`, agent projections, and
  record-replay / recomputation are **re-creatable caches** derived from it.
- **Fog:** agent projections carry only their own authorized view's digest; full-state/private
  digests, `master_seed`, and raw draw values are adjudicator-only; a draw value is revealed only
  **after** commands are committed.

## Error codes (WP-E1)

`missing-schema-version`, `missing-field`, `wrong-type`, `idempotency-key-mismatch`,
`reduce-mismatch` (PASS#9), `decorative-seed` (`rng` present with no draw), `successor-exists`,
`digest-domain-mismatch`, `not-byte-identical` (retry conflict).

## Limitations / deferred

One turn, single-writer, `local-posix-fs-v1`. Multi-turn chaining, multi-host/network-fs durability,
LLM-step records (`llm_steps`), branching, and the engine→prose `MODEL_OUTPUT` bridge are deferred.

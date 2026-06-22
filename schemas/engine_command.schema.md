# Engine command schema (v1) — typed agent actions

Contract for an engine **command registry** (`commands.yaml` under a scenario). A command is a
typed, immutable action an agent submits for one turn; the deterministic `validate_all` step decides
legality (an LLM may later *produce* commands and *explain* a rejection, but **never** decides
legality or mutates state). **No validator yet** — WP-E0 freezes this contract; `validate_all` +
golden-vector tests arrive in WP-E1. See [docs/ENGINE_CONTRACT.md](../docs/ENGINE_CONTRACT.md).

## Registry shape

```yaml
schema_version: "1.0"
commands:
  - command_id: cmd-blue-001        # client-supplied; AUDIT ONLY (never part of RNG identity)
    turn: 0
    actor_id: BLUE
    action_type: DISPATCH_SUPPLY    # DISPATCH_SUPPLY | BLOCK_ROUTE
    params: {quantity: 30, route: r1}
  - command_id: cmd-red-001
    turn: 0
    actor_id: RED
    action_type: BLOCK_ROUTE
    params: {route: r1}
```

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `commands` | yes | list | may be empty (an **empty turn is legal**); **≤ 1 command per `actor_id`** |
| `command_id` | yes | string | non-empty; unique; **audit only** — not used to address the RNG (see below) |
| `turn` | yes | integer | matches the turn being resolved |
| `actor_id` | yes | enum | `BLUE` \| `RED` |
| `action_type` | yes | enum | `DISPATCH_SUPPLY` \| `BLOCK_ROUTE` |
| `params` | yes | mapping | shape depends on `action_type` (below) |

### `params` by `action_type`

| action_type | params | Rule |
|---|---|---|
| `DISPATCH_SUPPLY` | `{quantity: int, route: str}` | `1 ≤ quantity ≤ 30`; `route ∈ {r1, r2}` |
| `BLOCK_ROUTE` | `{route: str}` | `route ∈ {r1, r2}` (blocking the unblockable `r2` is **legal but has no effect**) |

## Legality (deterministic `validate_all`, zero mutation, reject-all-or-resolve)

Rejected with **no state mutation and no committed turn record** (PASS#3): `quantity` outside
`[1,30]`, unknown `route`, an unknown `action_type`, or **more than one command per actor**. A
rejection is all-or-nothing — no partial application.

## Canonical ordering & RNG identity

The accepted batch is sorted by a **total order**: lexicographic over each command's canonical-JSON
bytes (`canon-v1`), so submission/file order is provably irrelevant (PASS#1). RNG identity is derived
from an **engine-owned semantic fingerprint** — `command_id` is **excluded** from the RNG address, so
resubmitting the same semantic action under a new `command_id` cannot reroll (PASS#11).

## Error codes (WP-E1)

`missing-schema-version`, `missing-field`, `wrong-type`, `invalid-enum`, `out-of-range`
(`quantity`), `unknown-route`, `too-many-commands` (> 1 per actor), `duplicate-command-id`.

## Limitations / deferred

One turn, ≤ 1 command per actor, two routes. Conditional/contingent orders, multi-command actors,
and LLM-produced commands are deferred.

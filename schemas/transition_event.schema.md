# Transition event schema (v1) — the ordered events of a turn

Contract for the engine's **transition events** — the ordered record of what happened in a turn,
carried inside a [turn record](turn_record.schema.md). `reduce(start_state, event_batch)` is the
**sole** constructor of the next state, so these events must carry enough payload to reproduce the
resulting state **without** consulting the resolver's reasoning or any hidden value. **Enforced** by each
resolver's `reduce()` (per-resolver `event_type` vocabularies — see below) + the turn-replay gate +
golden-vector tests; there is no standalone `validate_transition_event.py` (the event grammar is
resolver-specific, so `reduce()` is the enforcer).

> **Namespace firewall.** This is **NOT** the factbase evidence [`event`](event.schema.md) (which
> carries a DIME `category` and resolves to claims). A *transition* event is a distinct kind with its
> own `event_type` enum and its own validator; it must never reuse `event.schema.md`,
> `validate_events.py`, the DIME category enum, or `factbase/events.yaml`.

## Shape (an ORDERED sequence — `canon-v1` PRESERVES this order)

```yaml
schema_version: "1.0"
events:
  - {event_id: ev-001, turn: 0, event_type: SUPPLY_DISPATCHED,     route_id: r1, quantity: 30, source_command_id: cmd-blue-001}
  - {event_id: ev-002, turn: 0, event_type: ROUTE_BLOCK_ATTEMPTED, route_id: r1,               source_command_id: cmd-red-001}
  - {event_id: ev-003, turn: 0, event_type: SUPPLY_LOST,           route_id: r1, quantity: 30, draw_ref: draw-001}
```

## Fields

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | yes | string | non-empty |
| `events` | yes | list | an **ordered** sequence (may be empty for an empty turn); order is significant and hashed |
| `event_id` | yes | string | non-empty; unique within the batch |
| `turn` | yes | integer | matches the turn |
| `event_type` | yes | enum | one of the four below |
| `route_id` | conditional | string | required for all four slice event types; `∈ {r1, r2}` |
| `quantity` | conditional | integer | required for `SUPPLY_DISPATCHED`/`DELIVERED`/`LOST`; absent for `ROUTE_BLOCK_ATTEMPTED` |
| `source_command_id` | conditional | string | the command that produced the event (audit) |
| `draw_ref` | conditional | string | required iff a stochastic outcome consumed a draw (the `LOST`/`DELIVERED` terminal of a contested r1 dispatch); references a `draw_record` |

## `event_type` enum (per resolver)

The `event_type` vocabulary is **resolver-specific** — each resolver's `reduce()` enforces its own
grammar; there is no global enum. The table/grammar above is the **contested_logistics** vocabulary.

- **contested_logistics:** `SUPPLY_DISPATCHED`, `ROUTE_BLOCK_ATTEMPTED`, `SUPPLY_DELIVERED`, `SUPPLY_LOST`
  (stochastic terminals consume a `draw_ref`).
- **ru_ua_salvo_homogeneous (WP-E2a):** `STRIKES_LAUNCHED`, `INTERCEPTS_EXPENDED`, `STRIKES_INTERCEPTED`,
  `STRIKES_LEAKED`, `RESUPPLY` (`side`), `CULMINATION_STATUS` — deterministic (no draws).
- **ru_ua_salvo_heterogeneous (WP-E2b1):** per-threat / per-interceptor-type discriminated —
  `STRIKES_LAUNCHED` / `STRIKES_INTERCEPTED` / `STRIKES_LEAKED` / `RESUPPLY_STRIKE` (carry `threat`);
  `INTERCEPTS_EXPENDED` / `RESUPPLY_INTERCEPTOR` (carry `interceptor_type`); `BALLISTIC_LEAK_BAND` (the
  exogenous sensitivity band — reporting-only, a `reduce()` no-op); `LETHALITY_STATUS` (effective rate +
  sustained-k streak); `MAGAZINE_STATUS` (the weeks-of-supply leading indicator); `CULMINATION_STATUS`;
  and `TURN_ADVANCED` (`to_turn` — the multi-turn advance applied by `reduce()`). Deterministic (no draws).

## Event grammar (`reduce()` rejects violations)

Fixed order per turn: `SUPPLY_DISPATCHED` → `ROUTE_BLOCK_ATTEMPTED` → terminal
(`SUPPLY_DELIVERED` | `SUPPLY_LOST`). `reduce()` rejects: a terminal whose `route_id`/`quantity`
disagrees with its dispatch, a duplicate terminal for one dispatch, two terminals, or an illegal
order — **even if aggregate conservation happens to hold**.

### `reduce()` semantics (one case per type)
```
SUPPLY_DISPATCHED(r,q):     blue_supply.origin -= q;     blue_supply.in_transit += q
SUPPLY_DELIVERED(r,q):      blue_supply.in_transit -= q; blue_supply.delivered += q
SUPPLY_LOST(r,q):           blue_supply.in_transit -= q; blue_supply.loss_sink += q
ROUTE_BLOCK_ATTEMPTED(r):   no materialized-state change
```
`reduce()` needs **only** the events — never the hidden `block_threshold` or the raw draw (the
resolver consumed those to *choose* the terminal; the event encodes the *outcome*).

## Error codes (WP-E1)

`missing-schema-version`, `missing-field`, `wrong-type`, `invalid-enum`, `duplicate-event-id`,
`route-mismatch`, `quantity-mismatch`, `duplicate-terminal`, `illegal-order`, `dangling-draw-ref`.

## Limitations / deferred

The logistics slice is four event types, one interaction per turn. WP-E2a/E2b1 add the deterministic
salvo vocabularies (above), incl. the multi-turn `TURN_ADVANCED`. Stochastic salvo terminals (a draw per
intercept) and agent-facing salvo commands are deferred (WP-E2d / a later agent WP); delayed/triggered
events remain deferred.

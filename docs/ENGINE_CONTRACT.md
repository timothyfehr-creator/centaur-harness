# Engine contract (WP-E0 design-freeze)

The normative contract the engine implements. Frozen in WP-E0 (this doc + the typed schema docs +
hand-authored golden vectors); **implemented and enforced in WP-E1** (validators, `reduce()`, the
turn-replay gate, the 12-condition test suite). It is the product of three adversarial review rounds.
**Status (Constitution §3):** WP-E0 is contract-only — no engine runtime exists yet; nothing here is
enforced until WP-E1 ships its validators. Versioned artifacts (`canon-v1`, `rng-address-spec-1`, each
`schema_version`) are **immutable once a golden vector ships** — any change is a new `vN+1`.

Schemas: [engine_state](../schemas/engine_state.schema.md) ·
[engine_command](../schemas/engine_command.schema.md) ·
[transition_event](../schemas/transition_event.schema.md) ·
[turn_record](../schemas/turn_record.schema.md).

## Keystone — one durable authority

A single committed **[turn record](../schemas/turn_record.schema.md)** is the sole authority. The
typed `engine_state`, every per-agent projection, and all three replay tiers are **derived caches**
computed from that one object, consulting no other authority. **`reduce(start_state, event_batch)` is
the sole state constructor** — the resolver emits events only; it never writes state fields directly,
so there is no second authority to disagree. `reduce()` needs only the events (never the hidden
threshold or the raw draw).

## Replay tiers (never the bare word "replay")

- **record-replay** — re-derive state from the logged `event_batch` via `reduce()`; zero external
  calls, zero RNG draws.
- **recomputation** — re-run the resolver from `start_state` + recorded commands + the `rng` block;
  byte-exact `event_batch`/`resulting_state` in the pinned env (achievable because the slice is
  float-free, stdlib `hashlib` + JSON-canonical).
- **regeneration** — call an LLM again; not exact. **Not applicable** to this slice (no LLM).

## Resolution decision table (TOTAL over the command cross-product)

Two routes `r1, r2`. **One** adjudicator-private property: `block_threshold` on `route_secret:r1`
(`int 0–99`, `ASSUMED`). **`r2` is unblockable.** A d100 is consumed **iff** a `BLOCK_ROUTE` targets a
route that was `DISPATCH`-ed this turn **and** has a `block_threshold` — i.e. only `dispatch r1 + block r1`.
**Block succeeds iff `d100 < block_threshold`** (d100 ∈ **0–99**).

| dispatch ↓ \ block → | none | r1 | r2 |
|---|---|---|---|
| **none** | empty turn* | `BLOCK_ATTEMPTED(r1)`, no effect, no draw | `BLOCK_ATTEMPTED(r2)`, no effect, no draw |
| **r1** | `DISPATCHED(r1,q)`,`DELIVERED(r1,q)`, no draw | `DISPATCHED(r1,q)`,`BLOCK_ATTEMPTED(r1)`,**draw**; `d100<T`→`LOST(r1,q)` else `DELIVERED(r1,q)` | `DISPATCHED(r1,q)`,`BLOCK_ATTEMPTED(r2)`,`DELIVERED(r1,q)`, no draw |
| **r2** | `DISPATCHED(r2,q)`,`DELIVERED(r2,q)`, no draw | `DISPATCHED(r2,q)`,`BLOCK_ATTEMPTED(r1)`,`DELIVERED(r2,q)`, no draw | `DISPATCHED(r2,q)`,`BLOCK_ATTEMPTED(r2)`,`DELIVERED(r2,q)`, no draw |

\* **Empty turn (both none): LEGAL** — commits a record with empty `event_batch`,
`resulting_state == start_state`, no draw. Distinguished from a **rejected** command (which commits
**no** record). Invalid commands (`quantity` ∉ [1,30], unknown route, >1 per actor) → rejected,
zero mutation, no record. Fixed event order: `DISPATCHED` → `BLOCK_ATTEMPTED` → terminal.

## Transition protocol (phase order)

```
parse → validate_all (zero mutation, reject-all-or-resolve)
      → canonical command sort (lexicographic over canon-v1 bytes — total)
      → derive draw_plan (structural: from commands + ruleset; no threshold/roll)
      → transition_input_hash  (rng_request = null iff draw_plan empty)
      → resolve (draws via the random oracle; resolver alone reads block_threshold)
      → reduce(start_state, event_batch)   (sole constructor; rejects malformed batches)
      → invariant check (conservation, non-negativity) on the reduced state
      → commit to the successor_slot (O_EXCL) → derive caches
```
Validation **or** post-reduce invariant failure ⇒ **no record, no slot, no cache**.

## Commit identity, durability, idempotency

- **`transition_input_hash` (candidate_id)** = `engine_canonical_digest` over {`start_state`, sorted
  `command_batch`, `ruleset_version`, `resolver_id`+version, `ruleset` (the resolver's int-only params,
  or **null**), `rng_request` (or **null**), all `schema_version`s, `canon_version`}. A no-draw turn is
  therefore **seed-independent**; a different `ruleset` ⇒ a different candidate.
- **`successor_slot`** (e.g. `run/turns/0001.json`) enforces one successor per head via **`O_EXCL`
  create** (NOT `os.replace`, which replaces, not create-if-absent). Slot empty → commit; same
  candidate + byte-identical → idempotent success; different candidate → `successor-exists`.
- **Durability** (`persistence_profile: local-posix-fs-v1` — single-host crash + power-loss; not
  multi-host/network-fs): write tmp in the **same dir** → `flush + fsync(file)` → `os.replace` (cache
  writes) / `O_EXCL` (the slot) → **`fsync(parent dir)`**. Append-only retry: existing record ⇒
  **byte-identical-or-FAIL**.

## Canonicalization (`canon-v1`)

Normalize schema-declared **UNORDERED** collections (sort); **PRESERVE** schema-declared **ORDERED**
sequences (the `event_batch`). Canonical bytes = `json.dumps(obj, sort_keys=True,
separators=(',',':'), ensure_ascii=False).encode('utf-8')` over a typed subset of
`int/str/bool/null/ordered-list/object`; **reject** floats/NaN/inf/duplicate-keys/YAML-aliases/tags at
ingestion. This is JCS for the float-free subset — **no RFC-8785 dependency**. (YAML is a human
surface; it is **never** the hashed object — `json` is the canonical form.)

**Two digest domains, deliberately distinct:** the run-ledger's `content-raw` (raw bytes; reformatting
= drift; correct for input pinning) vs the engine's `canonical` (normalizes formatting so
logically-equal states hash equal). Digests are typed `{algorithm, domain, value}`; two named
functions (`ledger_content_digest` vs `engine_canonical_digest`); never an untyped `hash` field.
State is an envelope `{schema_version, state, state_digest}` with `state_digest` over the `state` field
**only** (self-reference excluded).

## RNG (`rng-address-spec-1`)

Identity = an engine-owned **semantic interaction fingerprint**: `(turn, phase, actor_id,
action_type, target_route, draw_name, draw_index, resolver_id, rng_namespace='root')` — **no client
`command_id`** (else a resubmit rerolls). The `master_seed` lives in **one** place (the binding, not
the address). Binding: `raw = sha256(domain_tag ‖ seed_bytes ‖ len(addr_json) ‖ addr_json)`;
`raw_uint = int.from_bytes(raw[:8], 'big')`; `d100 = raw_uint % 100` ∈ 0–99 (modulo bias ≈ 5e-18 at
64-bit — documented, **no rejection sampling**). `rng_namespace='root'` is a reserved constant (frozen
in the golden vector) so future common-random-number / branch use is a value change, not a `canon` bump.

**`PYTHONHASHSEED=0`** is set in the **launcher/CI environment** (not Python code — it is read at
interpreter startup) and asserted at startup (fail-closed). The canonicalization-robustness test runs
under `PYTHONHASHSEED ∈ {0,1,17}` via a dedicated **test entry point** that bypasses only that guard.

## Fog / event-projection policy

The authoritative record holds everything. Agent projections carry **only** their own authorized
view's digest; full-state digests, private-projection digests, `master_seed`, the semantic draw
address, and **raw draw values are adjudicator-only** (the raw draw is for audit/recomputation, not
agent visibility). A draw value is revealed only **after** commands are irreversibly committed.
**Recommended:** BLUE does **not** see RED's `ROUTE_BLOCK_ATTEMPTED` when the block fails (else a
failed block leaks RED's action). No-leak fixture: *RED idle* vs *RED blocks r1 and fails* project to
byte-identical BLUE bytes; varying the hidden threshold at a fixed outcome likewise. (A published
`LOST` at roll `r` leaks `threshold > r` — the game outcome; the multi-turn search-oracle is out of
scope for one turn but the policy is frozen so multi-turn inherits no accidental oracle.)

## WP-E1 acceptance — the 12 PASS conditions

1. Reorder command files → identical hashes. 2. Same manifest → identical bytes, fresh subprocess,
seeds {0,1,17}, `PYTHONHASHSEED=0` external. 3. Invalid command (quantity 0/>30, double, unknown
route) → **no record, head unchanged, caches byte-identical** (not merely `start==result`; the empty
turn legally has `start==result` *with* a record). 4. No adjudicator-only field/digest/seed/count/length
in any agent projection (incl. the RED-failed-block fixture). 5. Delete caches → re-derive
byte-identical via `reduce()`; no double-apply. 6. Every draw carries address+raw+rule_id. 7. Change
one action or the seed → different `transition_input_hash` (only when a draw is involved) and only
causally-affected events. 8. Ordered event sequence asserted; `rng` absent when no draw. 9.
`reduce(committed start, committed events) == committed resulting bytes`, via an independent verifier.
10. Single-successor-per-head (`O_EXCL` → `successor-exists`). 11. `command_id` change → no reroll.
12. Recompute every draw from seed+address, re-resolve → byte-identical `draw_records` + `event_batch`;
every stochastic terminal references exactly one consumed draw and vice versa.

## Recorded design decisions

d100 0–99; block iff `d100 < threshold`; total loss; quantity ∈ [1,30]; **r2 unblockable** (one
secret); empty turn legal-and-committed; RED's failed block **not** observable to BLUE; golden vectors
**hand-authored** from this table (not generated by the engine; source identity recorded in the test
manifest, not bound into the vector); engine on its own worktree branch (`engine-wp`), branch-local
commits, single post-WP9 merge with a one-time lockfile regenerate+re-sign.

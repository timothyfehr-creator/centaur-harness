# Engine contract (WP-E0 design-freeze)

The normative contract the engine implements. Frozen in WP-E0 (this doc + the typed schema docs +
hand-authored golden vectors); **implemented and enforced in WP-E1** (validators, `reduce()`, the
turn-replay gate, the 12-condition test suite). It is the product of three adversarial review rounds.
**Status (Constitution §3):** the contract is **implemented and enforced** — WP-E1 shipped the
validators, `reduce()`, the turn-replay gate (incl. a `transition_input_hash` recompute) and the
12-condition suite; WP-E2a added the homogeneous salvo resolver, `validate_engine_state.py` (ECI-2) and
the agent-view allowlist guard (ECI-1). "Frozen contract" (immutable) is distinct from "enforcement
live" (now true). Versioned artifacts (`canon-v1`, `rng-address-spec-1`, each `schema_version`) are
**immutable once a golden vector ships** — any change is a new `vN+1`.

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
**no** record). Invalid commands (`quantity` ∉ [1,30], unknown route, >1 per actor, unknown
`actor_id` (not `BLUE`/`RED`), or an actor issuing the other's action — `BLUE` may only
`DISPATCH_SUPPLY`, `RED` may only `BLOCK_ROUTE`) → rejected, zero mutation, no record. Fixed event order: `DISPATCHED` → `BLOCK_ATTEMPTED` → terminal.

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
manifest, not bound into the vector). The engine WPs (WP-E0 → WP-E2a + the ECI hygiene fixes) landed
**linearly on `main`** — the once-planned `engine-wp` worktree / single post-WP9 merge topology was not
used.

## Offline agent substrate (WP-A1a)

The agent layer's ONE SEAM: an LLM player's only engine write is the `commands` argument to
`turn_record.assemble`. The OFFLINE substrate exercises that seam with **hand-authored response bytes**
standing in for a model — **zero network, no model call ever** — so the whole pipeline is deterministic
and replayable.

- **Extract** (`core/command_extractor.py`): raw provider bytes → exactly `{action_type, params}` or a
  pinned rejection. Well-formedness ONLY (never legality, never identity). Strict: never take-first on
  ambiguity, never repair. A rejection is a recorded **FORFEIT** → the slot resolves NO_OP (an empty
  turn is legal).
- **Bind** (the harness, not the model): `actor_id = calling_slot`, `command_id = f"{run_id}:{turn}:
  {actor_id}"`, `turn = head.as_of_turn`. The model authors the SEMANTIC choice; the harness stamps the
  IDENTITY.
- **Referee**: `agent_logistics` (the turn-advancing contested-logistics resolver) adjudicates;
  `validate_all` enforces actor-enum + role/action capability + value ranges (strict, all-or-nothing) so a
  cross-role / out-of-range / unknown-actor command is REJECTED, never accepted-then-inert.
- **Forfeit-recovery** (WP-A2a): a well-formed command the referee rules ILLEGAL (e.g. an out-of-range
  quantity, or RED issuing DISPATCH_SUPPLY) does NOT crash the turn — the DRIVE pre-screens legality
  (`resolver.command_legality` on the harness-bound command) and forfeits just that slot to NO_OP, recorded
  as the third disposition **`ILLEGAL_FORFEIT`** (it carries the extracted-command digest + the resolver
  legality code, both re-verified by the provenance gate). The resolver stays the strict authority + backstop;
  the policy "an illegal move forfeits the mover" lives in the drive. So `step_kind` is one of **COMMAND**
  (legal) / **FORFEIT** (bytes not well-formed) / **ILLEGAL_FORFEIT** (well-formed but engine-illegal).
- **Provenance** (NON-CAUSAL): a flat `llm_step` per (turn, slot) in `run_ledger.llm_steps`, with the
  raw bytes content-addressed under `run/llm/{sha}.json`. Absent from `transition_input_hash`, so it
  cannot change replay.

The three replay/binding tiers (all on recorded bytes — a model is never re-called):
1. **record-replay + recomputation** — `validate_turn_replay` re-runs the engine on the recorded
   `command_batch` → byte-identical record (+ the chain check across a campaign).
2. **byte integrity** — `validate_agent_provenance` Tier-1: the content-addressed bytes re-hash to the
   recorded `response_sha256`.
3. **H7 binding** — `validate_agent_provenance` Tier-2 + H7a/H7b: re-extract from the bytes (at the
   recorded `extractor_version`, or fail closed) and assert `canonical_digest(project_semantic(committed
   command)) == that recompute`, plus the literal harness-bound identity asserts, plus COVERAGE (every
   committed agent command has a backing step). A SELF-CONSISTENT tamper passes replay but fails here.

`validate_agent_fog` adds the differential no-leak check (a viewer's projection is a function of public
state + outcome, never of the secret threshold value). **Disclosed residual:** a fully self-consistent
fabrication binds green — the gates prove internal consistency, not that the bytes authentically came
from a model (authenticity is unprovable under current APIs; the prompt↔envelope binding re-render is
deferred to the live lane WP-A1b).

## Offline machinery for a live call (WP-A1b) — built + gated; the live CALL is deferred

WP-A1b builds, fully offline and green-gated, everything a future single live model call needs — but does
**not** make the call (no network client, no spend, no Slice-0 probe). The substrate still only replays
hand-authored bytes; no model is ever called. What landed:

- **Prose-free at the SOURCE** (`core/response_redact.py`): a model response's committed bytes are an
  ALLOWLIST — only `tool_use` blocks survive, each PROJECTED to its `{type,id,name,input}` skeleton (a
  model-authored sibling field is dropped), plus allowlisted top-level keys; every `text`/`thinking`/other
  prose-bearing block is dropped *before hashing*. The full wire bytes (which hold the strategic prose) are
  never committed. `scripts/validate_no_prose.py` (RELEASE-wired) scans **every committed file** — at the top
  level, nested under a key, inside a JSON array, or behind a BOM — and fails closed on prose in any
  non-`tool_use` block, a `tool_use` sibling field, or a `tool_use` `input` outside the command enum tokens
  — closing the WP-A0 transcript disqualifier at the source, not by convention.
- **Closed-params extractor** (`EXTRACTOR_VERSION = "2"`): `submit_command.input` is a closed per-action
  schema (`DISPATCH_SUPPLY {quantity:int, route:enum}`, `BLOCK_ROUTE {route:enum}`) — no free-form/rationale
  field is expressible, so the command channel cannot smuggle prose.
- **Template registry** (`core/prompt_templates.py`): the versioned, content-pinned request render shared by
  the (deferred) live producer and the binding gate. PURE — no clock/nonce/network/float. Two structural
  honesty checks: the **differential-purity invariant** (vary the secret → the fixed system+tools bytes are
  unchanged) and a **secret-sentinel scan** (no hidden-surface value reaches the request bytes).
- **Tier-3 request-envelope binding** (`validate_agent_provenance`): a step rendered from a registered +
  **approved** template is re-rendered from the committed decision head's fog view and bound by sha256 —
  catching a self-consistent request tamper Tier-1 cannot. Dispatch fails closed on an unknown /
  registered-but-unapproved version. The offline synthetic envelope keeps the reserved `INTEGRITY_ONLY`
  version (Tier-1 re-hash only). **The binding is one leg of a THREE-LEGGED AND** (binding ∘ fog no-leak ∘
  template purity); alone it is *not* a no-leak proof — a leaky-but-registered template binds green, which
  **the audited allowlist + the purity invariant** catch (a registered-but-unapproved leak fails the
  allowlist; a state-derived leak fails the differential/sentinel scan; the render signature excludes secret
  args, so a *parameterized* leak is structurally impossible; a hardcoded constant in an approved template is
  caught only by human audit of the version change — disclosed as structural-not-proven). **Binding boundary
  (amendment 6):** it binds the recorded **client request body** = `render(prompt_version, fog_view)`
  (canonical content, not provider wire bytes); excludes the api-key + TLS; provider-side tool scaffolding
  (Anthropic's auto tool-use system prompt) is outside the client request, assumed non-secret-bearing, *not
  proven*; and it holds only under no provider-side prompt caching / no gateway-or-proxy injection / no
  SDK-default system augmentation — it is tamper-evidence relative to a *trusted capture pipeline*.
- **Determinism boundary** (`scripts/validate_no_network_imports.py`, RELEASE-wired): a static AST scan
  fails closed if any `core/`/`scripts/` module imports a network library (static or literal-dynamic); the
  only exception is the by-path `@live` allowlist (absent today). Complemented by a runtime `sys.modules`
  guard test.

**Authenticity residual (unchanged, disclosed):** the gates prove internal CONSISTENCY, not byte
AUTHENTICITY — a fully self-consistent fabricated capture binds green. A captured live game would be a
`CAPTURE_ARTIFACT` (a deflationary label, not the shared `ILLUSTRATIVE`), single-turn, memoryless, n=1,
never decision-facing. The ensemble/transcript/judge layers stay **INDEPENDENTLY NO-GO'd** (guarded by
`tests/test_verify_reporting_guard.py`).

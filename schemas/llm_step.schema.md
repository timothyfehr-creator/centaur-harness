# llm_step schema (WP-A1a) — non-causal agent-provenance entry

An `llm_step` records ONE (turn, slot) the agent boundary was called for, in the run-ledger's
`llm_steps` list. It is **NON-CAUSAL**: it is absent from `turn_record.transition_input_hash`'s
preimage (the engine never reads it), so populating `llm_steps` cannot change replay/recompute — the
turn-replay gate needs zero edits. It is the audit trail that binds the model's recorded SEMANTIC choice
to the committed command (see `validate_agent_provenance.py`, the H7 binding).

The raw byte artifacts (the response, including a forfeit's, and the request envelope) are content-
addressed under the scenario's `run/llm/{sha}.json`. Every `llm_step` field is a SCALAR **except the one
nested container `prior_attempts`** (the retry audit trail, below); the only other container is the
`llm_steps` list itself. (A separate, human-readable `run/forfeits/` audit record per forfeit is a
deferred follow-up; today a forfeit is fully reconstructible from its `response_sha256` bytes +
`reject_code`, which the gate re-derives.)

### Retry (WP-A2): the decisive attempt binds; rejected prior attempts are an audit trail

When live model-RETRY is enabled, a (turn, slot) may take several attempts: a rejected order is handed back
to the model with the public reject code (a `correction`) and re-asked, up to a bounded budget, before
falling back to FORFEIT/ILLEGAL_FORFEIT. The `llm_step` still records exactly the **DECISIVE** attempt (the
one that produced the COMMAND, or — if the budget is exhausted — the final forfeit), so the gate's 1:1
(turn, slot) cardinality and command coverage are unchanged. The earlier REJECTED attempts are recorded in a
**non-binding, gate-VERIFIED** `prior_attempts` list: each carries its own content-addressed redacted bytes,
and `validate_agent_provenance.py` re-extracts each one and confirms it GENUINELY rejects (so a retry cannot
be fabricated, and a legal-but-discarded attempt cannot be hidden). The `correction` field (on the step and
on each prior attempt) is the reject code that prompted **that** attempt (`null` for the first attempt); the
gate checks the correction chain is consistent (attempt K's `correction == ` attempt K-1's `reject_code`) and
re-renders each request with its `correction` to bind `request_envelope_sha256`.

## Example (a HAND_AUTHORED_FIXTURE COMMAND step)

```yaml
llm_steps:
  - schema_version: "1.0"
    run_id: "demo-001"
    turn: 0
    recorded_turn: 0
    calling_slot: "BLUE"
    command_id: "demo-001:0:BLUE"
    step_kind: "COMMAND"
    capture_mode: "HAND_AUTHORED_FIXTURE"
    provider: "anthropic"
    model: "N/A_FIXTURE"
    model_version: "N/A_FIXTURE"
    served_model: "N/A_FIXTURE"
    sampling: "PROVIDER_DEFAULT_NO_SEED"
    prompt_version: "v1"
    extractor_version: "1"
    canon_version: "canon-v1"
    response_sha256: "<64 hex>"
    request_envelope_sha256: "<64 hex>"
    extracted_command_digest: "<64 hex>"   # present for COMMAND + ILLEGAL_FORFEIT; null iff FORFEIT
    reject_code: null                       # null iff COMMAND; extractor code (FORFEIT) | legality code (ILLEGAL_FORFEIT)
    as_of: "2026-06-27"
```

## Fields (all scalar)

| field | rule |
|---|---|
| `schema_version` | `"1.0"` |
| `run_id` | non-empty string; the command_id namespace |
| `turn` | int; `== turn_record.turn` |
| `recorded_turn` | int; `== turn` (a redundant cross-check that catches a misfiled step) |
| `calling_slot` | enum **BLUE \| RED** — harness-set, never authored by the model |
| `command_id` | `f"{run_id}:{turn}:{calling_slot}"` (harness-derived; the H7b identity binding asserts this literally) |
| `step_kind` | enum **COMMAND \| FORFEIT \| ILLEGAL_FORFEIT** — the three content dispositions (legal / not-well-formed / well-formed-but-engine-illegal) |
| `capture_mode` | enum **LIVE \| HAND_AUTHORED_FIXTURE** — the offline substrate MUST be `HAND_AUTHORED_FIXTURE` (a fixture cannot masquerade as a real call) |
| `provider` | enum **anthropic** |
| `model` / `model_version` / `served_model` | string; pinned to `"N/A_FIXTURE"` when `capture_mode == HAND_AUTHORED_FIXTURE` (a fixture cannot claim a served model); free strings when LIVE |
| `sampling` | enum **PROVIDER_DEFAULT_NO_SEED** — the sole honest value (a fake `temperature: 0.0` is un-spellable, and it keeps the record float-free) |
| `prompt_version` | string; content-hashed template id (re-derivation selector; the prompt↔envelope binding re-render is the Tier-3 check, now ACTIVE — `validate_agent_provenance` re-renders the template over the committed fog view and binds `request_envelope_sha256`) |
| `extractor_version` | string; the binding re-derivation selector (Tier-2 dispatches to the RECORDED version or fails closed) |
| `canon_version` | string; `== canon.CANON_VERSION` |
| `response_sha256` | 64-hex; sha256 of the raw response bytes, hashed ONCE at record time |
| `request_envelope_sha256` | 64-hex; sha256 of the raw request body (integrity-only offline) |
| `extracted_command_digest` | 64-hex for **COMMAND + ILLEGAL_FORFEIT** (the command WAS extracted); **null iff** `step_kind == FORFEIT`; `canonical_digest(project_semantic(extract(bytes)))` |
| `reject_code` | **null iff COMMAND**; an EXTRACTOR code iff FORFEIT; a RESOLVER LEGALITY code iff ILLEGAL_FORFEIT (the gate re-derives it from the harness-bound command) |
| `correction` | **null** on the first attempt; else the reject code that prompted this (retry) attempt — a member of `CORRECTION_CODES` (extractor ∪ legality). The decisive request was rendered with it; the gate re-renders + binds |
| `prior_attempts` | absent or a (possibly empty) list of the REJECTED attempts before the decisive one this turn; each `{response_sha256, request_envelope_sha256, attempt_kind (FORFEIT\|ILLEGAL_FORFEIT), reject_code, correction}`. NON-binding but gate-VERIFIED (each must re-extract to a genuine reject; a LEGAL prior attempt is rejected) |
| `as_of` | ISO-8601 date |

## Pinned enums

- `calling_slot`: `BLUE`, `RED`
- `step_kind`: `COMMAND` (a legal command), `FORFEIT` (bytes not well-formed), `ILLEGAL_FORFEIT` (a well-formed command the engine ruled illegal → the slot forfeits to NO_OP)
- `capture_mode`: `LIVE`, `HAND_AUTHORED_FIXTURE`
- `provider`: `anthropic`
- `sampling`: `PROVIDER_DEFAULT_NO_SEED`
- `reject_code` (FORFEIT): `malformed-bytes`, `no-command`, `ambiguous-command`, `semantic-field-invalid`, `non-canon-command`, `unknown-action`, `params-schema-mismatch` (the `core.command_extractor.REJECT_CODES`)
- `reject_code` (ILLEGAL_FORFEIT): `unknown-actor`, `role-action-mismatch`, `too-many-commands`, `out-of-range`, `unknown-route`, `invalid-enum`, `insufficient-supply` (the `core.resolver.LEGALITY_REJECT_CODES` — a DISTINCT namespace; legality, not well-formedness)
- `correction` (retry): `null` (first attempt) or any `core.prompt_templates.CORRECTION_CODES` value (the extractor ∪ legality reject codes — the public reason a retry was prompted, never a secret)

## Validation split

`validate_run_ledger.py` enforces only a STRUCTURAL FLOOR (llm_steps is null or a non-empty list of
mappings, each with a 64-hex `response_sha256`) so a populated placeholder can't be present-but-
unvalidated. The DEEP shape + the H7 binding (semantic-digest equality + the three literal harness-bound
identity asserts) are owned by `validate_agent_provenance.py` (a release gate).

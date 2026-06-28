# llm_step schema (WP-A1a) — non-causal agent-provenance entry

An `llm_step` records ONE (turn, slot) the agent boundary was called for, in the run-ledger's
`llm_steps` list. It is **NON-CAUSAL**: it is absent from `turn_record.transition_input_hash`'s
preimage (the engine never reads it), so populating `llm_steps` cannot change replay/recompute — the
turn-replay gate needs zero edits. It is the audit trail that binds the model's recorded SEMANTIC choice
to the committed command (see `validate_agent_provenance.py`, the H7 binding).

The raw byte artifacts are content-addressed under the scenario's `run/llm/{sha}.json` (response and
request envelope) and `run/forfeits/` (a recorded forfeit), each pinned as a declared input in the
ledger. Every `llm_step` field is therefore a SCALAR (the only container is the `llm_steps` list itself).

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
    extracted_command_digest: "<64 hex>"   # null iff step_kind == FORFEIT
    reject_code: null                       # non-null iff step_kind == FORFEIT
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
| `step_kind` | enum **COMMAND \| FORFEIT** |
| `capture_mode` | enum **LIVE \| HAND_AUTHORED_FIXTURE** — the offline substrate MUST be `HAND_AUTHORED_FIXTURE` (a fixture cannot masquerade as a real call) |
| `provider` | enum **anthropic** |
| `model` / `model_version` / `served_model` | string; pinned to `"N/A_FIXTURE"` when `capture_mode == HAND_AUTHORED_FIXTURE` (a fixture cannot claim a served model); free strings when LIVE |
| `sampling` | enum **PROVIDER_DEFAULT_NO_SEED** — the sole honest value (a fake `temperature: 0.0` is un-spellable, and it keeps the record float-free) |
| `prompt_version` | string; content-hashed template id (re-derivation selector; the prompt↔envelope binding re-render is deferred to WP-A1b) |
| `extractor_version` | string; the binding re-derivation selector (Tier-2 dispatches to the RECORDED version or fails closed) |
| `canon_version` | string; `== canon.CANON_VERSION` |
| `response_sha256` | 64-hex; sha256 of the raw response bytes, hashed ONCE at record time |
| `request_envelope_sha256` | 64-hex; sha256 of the raw request body (integrity-only offline) |
| `extracted_command_digest` | 64-hex, or **null iff** `step_kind == FORFEIT`; `canonical_digest(project_semantic(extract(bytes)))` |
| `reject_code` | one of the extractor's pinned reject codes, or **null iff** `step_kind == COMMAND` |
| `as_of` | ISO-8601 date |

## Pinned enums

- `calling_slot`: `BLUE`, `RED`
- `step_kind`: `COMMAND`, `FORFEIT`
- `capture_mode`: `LIVE`, `HAND_AUTHORED_FIXTURE`
- `provider`: `anthropic`
- `sampling`: `PROVIDER_DEFAULT_NO_SEED`
- `reject_code`: `malformed-bytes`, `no-command`, `ambiguous-command`, `semantic-field-invalid`, `non-canon-command` (the `core.command_extractor.REJECT_CODES`)

## Validation split

`validate_run_ledger.py` enforces only a STRUCTURAL FLOOR (llm_steps is null or a non-empty list of
mappings, each with a 64-hex `response_sha256`) so a populated placeholder can't be present-but-
unvalidated. The DEEP shape + the H7 binding (semantic-digest equality + the three literal harness-bound
identity asserts) are owned by `validate_agent_provenance.py` (a release gate).

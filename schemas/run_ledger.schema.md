# Run-ledger schema (v1) — reproducibility provenance (CONSTITUTION §6)

Contract for a per-scenario `run_ledger.yaml` (e.g.
`examples/<name>/run_ledger.yaml`). Enforced by
[`scripts/validate_run_ledger.py`](../scripts/validate_run_ledger.py) (a CI step). The
ledger **pins** the provenance of a deterministic run over the scenario's declared inputs;
the validator is a **lockfile drift gate** — it checks the ledger's structure, then
recomputes the live input hashes and confirms the committed ledger still reproduces.
`--write` regenerates it.

## Shape

```yaml
schema_version: "1.0"
as_of_date: "YYYY-MM-DD"          # ISO-8601, validated
code_version: "<git sha>"         # git HEAD at --write time (+ "-dirty" if an input is uncommitted)
tool_version: "1.0"
generated_by: "validate_run_ledger.py --write"
inputs:                           # one {path, sha256} per declared input, sorted by path
  - {path: "<repo-root POSIX path>", sha256: "<64 lowercase hex>"}
rng_seeds: null                   # null: the engine is DETERMINISTIC (no RNG draws) — see Fields
llm_steps: null                   # null, OR a list of llm_step provenance entries (WP-A1a) — see Fields
```

## Fields

| Field | Required | §6 mapping | Rule |
|---|---|---|---|
| `schema_version` | yes | config/version | non-empty string |
| `as_of_date` | yes | as-of date | non-empty; strict ISO-8601 `YYYY-MM-DD` |
| `code_version` | yes | code version | non-empty (git HEAD sha; `-dirty` if an input is uncommitted) |
| `tool_version` | yes | config/version | non-empty (the validator's own version) |
| `generated_by` | yes | — | non-empty provenance breadcrumb |
| `inputs[].path` | yes | — | non-empty repo-root POSIX path |
| `inputs[].sha256` | yes | as-of/content | `^[0-9a-f]{64}$` (raw-bytes sha256) |
| `rng_seeds` | — | RNG seeds | must be `null` — the engine is DETERMINISTIC (no RNG draws); a stochastic resolver is a future REVIEWED WP, not an in-place change |
| `llm_steps` | — | model/version/prompt/temperature | `null` (no agent step) OR a non-empty list of `llm_step` provenance entries (WP-A1a), each carrying a 64-hex `response_sha256`. Structural floor only; deep shape + the H7 binding are owned by `validate_agent_provenance.py`. See [llm_step.schema.md](llm_step.schema.md). NON-CAUSAL (absent from `transition_input_hash`). |

## Declared inputs (the reproducibility surface)

The scenario's `scenario.yaml`, `agents.yaml`, `initial_state.yaml`, **`engine_state.yaml` +
`rules.yaml`** (engine scenarios — the typed compute surface + resolver params), its `state/`
partition (`public.yaml` + `private/*.yaml`), plus the repo-wide `factbase/*.yaml` and
`knowledge/**/*.yaml`. Resolved live and sorted by repo-root POSIX path (one canonical order). The
committed turn record (`run/turns/*.json`) is a derived **output**, gated by the turn-replay gate, so
it is **not** pinned here.

## Determinism & integrity contract

- The hash is **content-only** (raw file bytes, sha256) — deterministic across machines/CI.
  A reformatted-but-equivalent input (key reorder, comment change) **counts as drift** — that
  is correct lockfile behavior.
- `code_version` is **recorded, not re-derived**: the integrity check is content-hash-based and
  **git-independent** (works offline / in a non-git checkout). `code_version` is provenance
  metadata; the hashes are the authoritative integrity surface.
- `--write` emits with a pinned serializer (`yaml.safe_dump(sort_keys=False,
  default_flow_style=False, width=4096)`) so the committed bytes are stable.

## Error codes

Structure: `missing-field`, `invalid-format` (bad sha hex / bad ISO date / non-null
placeholder). Integrity (drift): `missing-input`, `extra-input`, `hash-mismatch`. Structure is
checked first; a structural fault short-circuits before the integrity check. Fail-closed (exit
2): an unreadable / non-mapping ledger, an absent `inputs` list, or zero declared inputs.

## ⚠ Lockfile discipline (read this)

The declared-input set is resolved by **live globs**. **Adding, editing, or removing any
declared-input file** (`factbase/*.yaml`, `knowledge/**/*.yaml`, `state/private/*.yaml`, or the
scenario's root files) makes the committed ledger stale, and CI fails with
`hash-mismatch` / `extra-input` / `missing-input`. The fix is a one-liner the failure prints:

```
.venv/bin/python scripts/validate_run_ledger.py --write   # then commit run_ledger.yaml
```

This drift gate is the point — it makes silent input changes impossible to land un-recorded.

## Deferred

No engine / RNG / LLM-call execution (the `null` placeholders are the entire forward-compat
surface), no signing/Merkle, no multi-run/history ledgers, no turn-replay (needs an engine),
no env/OS drift tracking. One ledger per scenario.

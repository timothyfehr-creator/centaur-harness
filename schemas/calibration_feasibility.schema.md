# Calibration-feasibility schema (v1) — the honest "cannot calibrate" record (WP-E2c)

Contract for a per-scenario **calibration-feasibility record**
(`examples/<scenario>/calibration_feasibility.yaml`): the on-the-record finding that a channel was
ATTEMPTED for calibration and **cannot** be calibrated against the available data, keeping
`signoff.calibration_status: UNCALIBRATED`. Enforced by
[`scripts/validate_calibration_feasibility.py`](../scripts/validate_calibration_feasibility.py)
(a CI step and the `release` gate). A flat single document — **not** a registry/list, **not** in
`SCHEMA_REGISTRY`.

This is **deliberately separate** from [`calibration.schema.md`](calibration.schema.md): that record
BACKS a `CALIBRATED` claim; this record DOCUMENTS the absence of a calibratable observable. The two never
collide — distinct filenames (`calibration.yaml` vs `calibration_feasibility.yaml`), distinct gates. The
invariant: *a model that can't be honestly calibrated SAYS SO, on the record* (CONSTITUTION §5 applied to
the absence of evidence). **STRUCTURAL + ATTESTATION ONLY** — a clean record means the non-feasibility
claim is well-formed and bound to the reproducible snapshot, not that anything is analytically valid.

## Shape

```yaml
schema_version: "1.0"
id: calfeas-001
target: ru_ua_salvo_heterogeneous   # the scenario this record concerns (== dir name)
code_version: "<run_ledger code_version>"
verdict: NOT_FEASIBLE               # NOT_FEASIBLE | INSUFFICIENT_DATA  (there is NO 'feasible' value)
attempted_observable: "kinetic drone intercept-% (shot_down / (launched - decoys - EW_lost)), weekly, Sept-Nov 2024"
binding_reasons:                    # >= 1 non-empty string -- WHY calibration is not feasible
  - "kinetic-vs-jammed split not separable: the UA-AF 'locationally lost' bucket is a composite ..."
  - "no method-independent corroboration: every quantitative source traces to the one UA-AF feed ..."
dossier_ref: "centaur_engine_planning/WP-E2c_DATA_DOSSIER.md@2026-06-23"
dossier_sha256: null                          # OPTIONAL -- a hash exists IFF dossier_sha256_status is PINNED
dossier_sha256_status: EXTERNAL_NOT_PINNED    # PINNED | EXTERNAL_NOT_PINNED | NOT_ATTEMPTED (#7-min)
upgrade_gap: "a method-independent (impact-site / visual-OSINT / satellite) intercept estimate -- none found"
authority: "WP-E2c data dossier (multi-source live web sweep, 2026-06-23)"
assessor: "<who / what assessed feasibility>"
feasibility_date: "2026-06-23"     # ISO-8601 YYYY-MM-DD
external_context:                  # OPTIONAL -- a labeled plausibility band, NEVER a validation/comparison
  observed_range_pct: [46, 77]     # a [low, high] pair in 0..100, ordered
  coverage: PARTIAL                # PARTIAL | FULL
  weeks_computed: 4                # <= weeks_in_window
  weeks_in_window: 14
  comparability_to_model_p: NONE   # NONE | INDIRECT | DIRECT  -- how comparable the band is to the model's p
  comparison_role: CONTEXT_ONLY    # the SOLE legal value -- the block is never an input to calibration
  calibration_effect: NONE         # the SOLE legal value -- the block moves no parameter
  source_class: SELF_REPORTED_BELLIGERENT
  labels: [SINGLE_SOURCE, COMPOSITE_BUCKET, NOT_CORROBORATED]
  caveat: "background context only; not a fit, not validated, not corroborated"
provenance:                        # OPTIONAL -- a hash exists IFF sha256_status is PINNED
  - dataset: "piterfm Russia-Ukraine war dataset (Petro Ivaniuk; via Kaggle)"
    version: "v196"
    sha256: null
    sha256_status: BLOCKED_FETCH_AUTH_GATED
    url: "https://www.kaggle.com/..."   # OPTIONAL
    snapshot_date: "2026-06-23"          # OPTIONAL
launch_denominator_conflict:       # OPTIONAL -- record an unreconciled denominator honestly
  status: UNRESOLVED
  values:
    - {month: "2024-09", launched: 1410, source: "ArmyInform/Gen-Staff 2024-11-05"}
    - {month: "2024-09", launched: 1331, source: "FM Sybiha via Ukrainska Pravda"}
```

## Fields

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | non-empty string |
| `id` | yes | non-empty string |
| `target` | yes | non-empty string; **must equal the scenario directory name** → `unresolved-scenario-ref` |
| `code_version` | yes | non-empty string; **must equal the scenario `run_ledger.yaml` `code_version`** → `stale-feasibility` |
| `verdict` | yes | enum `NOT_FEASIBLE` \| `INSUFFICIENT_DATA` → `invalid-enum`. **No `FEASIBLE` value by design** — a calibratable channel graduates to `calibration.yaml`/`CALIBRATED`, it does not flip a feasibility record |
| `attempted_observable` | yes | non-empty string (the quantity calibration was attempted on) |
| `binding_reasons` | yes | a **non-empty list of non-empty strings** → `empty-reasons` (absent → `missing-field`) |
| `dossier_ref` | yes | non-empty string (provenance pointer to the feasibility finding) |
| `dossier_sha256` / `dossier_sha256_status` | no | #7-min binding. `dossier_sha256_status` ∈ {`PINNED`,`EXTERNAL_NOT_PINNED`,`NOT_ATTEMPTED`}; `PINNED` ⇒ `dossier_sha256` is 64-hex (`invalid-format`); otherwise it MUST be `null` → `dossier-contradiction`. The dossier lives OUTSIDE the repo, so the honest value is `EXTERNAL_NOT_PINNED` + `null` (no fabricated hash; an in-repo copy + a full manifest are deferred) |
| `upgrade_gap` | yes | non-empty string (what would have to exist to ever calibrate) |
| `authority` | yes | non-empty string (who/what produced the feasibility assessment) |
| `assessor` | yes | non-empty string |
| `feasibility_date` | yes | ISO-8601 `YYYY-MM-DD` → `invalid-format` |
| `external_context` | no | if present: a mapping (replaces the retired `descriptive_band`). Carries machine-readable honesty fields, each REQUIRED: `comparison_role` (sole legal value `CONTEXT_ONLY`), `calibration_effect` (sole legal value `NONE`), `comparability_to_model_p` ∈ {`NONE`,`INDIRECT`,`DIRECT`}, `coverage` ∈ {`PARTIAL`,`FULL`}, `source_class` (enum), `caveat` (non-empty), `labels` (≥1 honesty marker → `unlabeled-band`), `observed_range_pct` (a `[low,high]` pair in 0..100, ordered → `out-of-range`), `weeks_computed`/`weeks_in_window` (ints, `weeks_computed ≤ weeks_in_window` → `out-of-range`). Unknown keys (e.g. a re-added `model_value_pct`) → `unknown-key`. No affirmative over-claim language anywhere → `over-claim-language` |
| `provenance` | no | if present: a list; each entry's keys ⊆ {`dataset`,`version`,`sha256`,`sha256_status`,`url`,`snapshot_date`} (else `unknown-key`); `sha256_status` ∈ {`PINNED`,`BLOCKED_FETCH_AUTH_GATED`,`NOT_ATTEMPTED`}; `PINNED` ⇒ `sha256` is 64-hex (`invalid-format`); otherwise `sha256` MUST be `null` → `provenance-contradiction` (no fabricated hashes) |
| `launch_denominator_conflict` | no | if present: `status` ∈ {`UNRESOLVED`,`RESOLVED`} + a non-empty `values` list; keys ⊆ {`status`,`values`,`note`} and each value's keys ⊆ {`month`,`launched`,`source`} (else `unknown-key`) |
| *(any level)* | — | **Unknown keys are rejected at every object level** (`unknown-key`) — the structural boundary that kills `matches_ground_truth`/smuggled-comparison bypasses a word scan can't enumerate |

## Contract — say-so-on-the-record (CONSTITUTION §5)

- The record only makes sense under a no-evidence label: the resolving `signoff.calibration_status` must
  be `UNCALIBRATED` / `ILLUSTRATIVE`; a feasibility record under `CALIBRATED` is a `contradictory-status`
  finding (you cannot simultaneously claim calibrated and record non-feasibility).
- **The disposition is enforced, not voluntary (WP-E2c.1 #2).** The gate is **signoff-driven**: a
  `signoff.calibration_disposition` of `NOT_FEASIBLE` / `INSUFFICIENT_DATA` **obliges** a record whose
  `verdict` equals the disposition (`disposition-mismatch`), whose `id` equals
  `signoff.calibration_feasibility_ref` (`unresolved-feasibility-ref`), and whose exact bytes hash to
  `signoff.calibration_feasibility_sha256` (`stale-feasibility-binding`). Deleting the record →
  `missing-feasibility-record`; a record present under a `NONE`/`CALIBRATED` disposition → `disposition-mismatch`.
  So "we cannot calibrate" can no longer be silently removed and still pass release.
- **No back-door calibration.** `verdict` has no "feasible" value; an `external_context` block is pinned by
  machine-readable enums to `comparison_role: CONTEXT_ONLY` + `calibration_effect: NONE` (it structurally
  cannot be an input to calibration or move a parameter) and may never affirm validation language; the only
  path to a positive calibration claim is `calibration.yaml` under `CALIBRATED`, whose proof-obligation in
  `validate_calibration.py` is left untouched.
- **Structure is the boundary, the word scan is defense-in-depth.** Unknown keys are rejected at every
  object level (`unknown-key`), so a smuggled `matches_ground_truth`/comparison field cannot ride along in a
  record the gate "doesn't look at"; the clause-aware over-claim word scan over the whole record is a
  second layer (honest negated disclaimers — "not corroborated", "never validated" — pass; an affirmative
  in any allowed free-text field fails).
- **No fabricated provenance.** A SHA exists only when actually `PINNED`; a blocked/un-attempted fetch
  records `sha256: null` + the status — the gap is flagged, not papered over.
- **Reproducibility binding (extends WP7/WP8).** `code_version` pins the run-ledger snapshot the
  assessment covers; a declared-input change regenerates the ledger → `stale-feasibility` (re-assess /
  re-record). The record is NOT itself a declared run-ledger input (binding is one-directional). See
  [run_ledger.schema.md](run_ledger.schema.md), [../docs/RUNBOOK.md](../docs/RUNBOOK.md).

## Error codes

`missing-schema-version`, `missing-field`, `invalid-enum`, `invalid-format`, `empty-reasons`,
`unknown-key`, `out-of-range`, `unlabeled-band`, `over-claim-language`, `provenance-contradiction`,
`dossier-contradiction`, `missing-feasibility-record`, `disposition-mismatch`, `unresolved-feasibility-ref`,
`stale-feasibility-binding`,
`wrong-type`, `unresolved-scenario-ref`, `stale-feasibility`, `contradictory-status`. Structure first (single-fault),
then resolution, then signoff consistency. Fail-closed (exit 2) on a missing/unreadable
scenario/ledger/signoff, or a present-but-unparseable feasibility record.

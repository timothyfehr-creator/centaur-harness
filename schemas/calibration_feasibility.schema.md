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
upgrade_gap: "a method-independent (impact-site / visual-OSINT / satellite) intercept estimate -- none found"
authority: "WP-E2c data dossier (multi-source live web sweep, 2026-06-23)"
assessor: "<who / what assessed feasibility>"
feasibility_date: "2026-06-23"     # ISO-8601 YYYY-MM-DD
descriptive_band:                  # OPTIONAL -- a labeled plausibility band, NEVER a validation
  model_value_pct: 80
  observed_range_pct: [46, 77]
  source_class: SELF_REPORTED_BELLIGERENT
  labels: [SINGLE_SOURCE, COMPOSITE_BUCKET, NOT_CORROBORATED]
  caveat: "descriptive plausibility check only; not calibrated, not validated, not corroborated"
provenance:                        # OPTIONAL -- a hash exists IFF sha256_status is PINNED
  - dataset: "piterfm Unmanned Systems Tracker"
    version: "v196"
    sha256: null
    sha256_status: BLOCKED_FETCH_AUTH_GATED
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
| `upgrade_gap` | yes | non-empty string (what would have to exist to ever calibrate) |
| `authority` | yes | non-empty string (who/what produced the feasibility assessment) |
| `assessor` | yes | non-empty string |
| `feasibility_date` | yes | ISO-8601 `YYYY-MM-DD` → `invalid-format` |
| `descriptive_band` | no | if present: a mapping; `labels` must include ≥1 honesty marker (`SINGLE_SOURCE`/`COMPOSITE_BUCKET`/`NOT_CORROBORATED`/`SELF_REPORTED`/`ILLUSTRATIVE`) → `unlabeled-band`; `source_class` enum-checked; **no over-claim language** (`calibrated`/`validated`/`corroborated`/`confirmed`/`verified`) → `over-claim-language` |
| `provenance` | no | if present: a list; each entry's `sha256_status` ∈ {`PINNED`,`BLOCKED_FETCH_AUTH_GATED`,`NOT_ATTEMPTED`}; `PINNED` ⇒ `sha256` is 64-hex (`invalid-format`); otherwise `sha256` MUST be `null` → `provenance-contradiction` (no fabricated hashes) |
| `launch_denominator_conflict` | no | if present: `status` ∈ {`UNRESOLVED`,`RESOLVED`} + a non-empty `values` list |

## Contract — say-so-on-the-record (CONSTITUTION §5)

- The record only makes sense under a no-evidence label: the resolving `signoff.calibration_status` must
  be `UNCALIBRATED` / `ILLUSTRATIVE`; a feasibility record under `CALIBRATED` is a `contradictory-status`
  finding (you cannot simultaneously claim calibrated and record non-feasibility).
- **No back-door calibration.** `verdict` has no "feasible" value; the band can never use validation
  language; the only path to a positive calibration claim is `calibration.yaml` under `CALIBRATED`, whose
  proof-obligation in `validate_calibration.py` is left untouched.
- **No fabricated provenance.** A SHA exists only when actually `PINNED`; a blocked/un-attempted fetch
  records `sha256: null` + the status — the gap is flagged, not papered over.
- **Reproducibility binding (extends WP7/WP8).** `code_version` pins the run-ledger snapshot the
  assessment covers; a declared-input change regenerates the ledger → `stale-feasibility` (re-assess /
  re-record). The record is NOT itself a declared run-ledger input (binding is one-directional). See
  [run_ledger.schema.md](run_ledger.schema.md), [../docs/RUNBOOK.md](../docs/RUNBOOK.md).

## Error codes

`missing-schema-version`, `missing-field`, `invalid-enum`, `invalid-format`, `empty-reasons`,
`unlabeled-band`, `over-claim-language`, `provenance-contradiction`, `wrong-type`,
`unresolved-scenario-ref`, `stale-feasibility`, `contradictory-status`. Structure first (single-fault),
then resolution, then signoff consistency. Fail-closed (exit 2) on a missing/unreadable
scenario/ledger/signoff, or a present-but-unparseable feasibility record.

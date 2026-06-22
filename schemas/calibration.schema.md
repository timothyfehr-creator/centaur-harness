# Calibration schema (v1) — the evidence-or-label record (WP9.1)

Contract for a per-scenario **calibration record**
(`examples/<scenario>/calibration.yaml`): the proper-scoring-rule evidence that backs a
`signoff.calibration_status: CALIBRATED` claim. Enforced by
[`scripts/validate_calibration.py`](../scripts/validate_calibration.py) (a CI step and the
`release` gate). A flat single document — **not** a registry/list, **not** in `SCHEMA_REGISTRY`.

**The harness RECORDS an externally / human-computed calibration result; it never COMPUTES one.**
Scoring a forecast against resolved outcomes needs the engine + outcome data (a non-goal, like
turn-replay). This gate checks the record is structurally complete, in-range, and bound to the
scenario's reproducible snapshot — it does not run a backtest.

## Shape (required only when `calibration_status` is `CALIBRATED`)

```yaml
schema_version: "1.0"
id: cal-001
target: ukraine_crimea_logistics   # the scenario this record scores
code_version: "<run_ledger code_version>"
metric: BRIER_SCORE                # BRIER_SCORE | LOG_LOSS | HIT_RATE
metric_value: 0.218
outcome_count: 48                  # N
outcome_authority: "GJP adjudication v3.1"
scoring_date: "2026-06-22"
forecaster: "<method / ensemble>"
baseline_value: 0.2275             # optional
# notes: "..."                     # optional
```

## Fields

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | non-empty string |
| `id` | yes | non-empty string |
| `target` | yes | non-empty string; **must equal the scenario directory name** → `unresolved-scenario-ref` |
| `code_version` | yes | non-empty string; **must equal the scenario `run_ledger.yaml` `code_version`** → `stale-calibration` |
| `metric` | yes | enum `BRIER_SCORE` \| `LOG_LOSS` \| `HIT_RATE` → `invalid-enum` |
| `metric_value` | yes | a **finite** number (not bool/NaN/Inf → `wrong-type`) **in the metric's range** → `invalid-range` |
| `outcome_count` | yes | integer **N > 0** (not bool/float → `wrong-type`; ≤ 0 → `invalid-range`) — N=0 is not auditable |
| `outcome_authority` | yes | non-empty string (who resolved the outcomes) |
| `scoring_date` | yes | ISO-8601 `YYYY-MM-DD` → `invalid-format` |
| `forecaster` | yes | non-empty string (the method / ensemble scored) |
| `baseline_value` | no | if present: a finite number in the same range (naive/base-rate comparison) |
| `notes` | no | string |

**Metric ranges** (per published scoring-rule definitions, *not* magic numbers): Brier (1950, the
mean squared error of probability forecasts) and `HIT_RATE` (GJP/Tetlock fraction-correct) are in
`[0, 1]`; the logarithmic score `LOG_LOSS` is in `[0, +inf)`. Submit values rounded to ≤ 10 decimals
(boundaries are inclusive and exact; no tolerance).

## Contract — evidence or label (CONSTITUTION §5)

- `calibration_status: CALIBRATED` **must** resolve to this record → else `unsupported-calibration`
  (a content finding that blocks release, like §5 `unsupported-baseline`).
- `UNCALIBRATED` / `ILLUSTRATIVE` need **no** record (the honest "UNCALIBRATED ANALYTICAL JUDGMENT"
  label). A record present under a non-CALIBRATED status is a contradiction → `consistency-note`.
- **STRUCTURAL + ATTESTATION ONLY.** A clean record means the calibration *claim* is evidence-backed
  and current, **not** that the analysis is valid (CONSTITUTION §3).
- **Reproducibility binding (extends WP7/WP8).** `code_version` pins the run-ledger snapshot the
  scoring covers. ⚠ **Lockfile discipline:** a declared-input change regenerates the ledger to a new
  `code_version` → this record goes `stale-calibration`; re-score / re-record and update
  `code_version`. See [run_ledger.schema.md](run_ledger.schema.md), [../docs/RUNBOOK.md](../docs/RUNBOOK.md).

## Error codes

`missing-schema-version`, `missing-field`, `invalid-enum`, `wrong-type`, `invalid-range`,
`invalid-format`, `unresolved-scenario-ref`, `stale-calibration`, `unsupported-calibration`,
`consistency-note`. Structure first (single-fault), then resolution. Fail-closed (exit 2) on a
missing/unreadable signoff/ledger/scenario, or a CALIBRATED claim whose present record can't be parsed.

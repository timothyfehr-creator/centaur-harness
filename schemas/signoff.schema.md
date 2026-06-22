# Signoff schema (v1) — the human approval attestation (WP8.1)

Contract for a per-scenario **signoff** artifact
(`examples/<scenario>/signoff.yaml`): a lightweight record that a human approved the scenario
package, bound to the **review** it accepts and the reproducible snapshot it approves. Enforced by
[`scripts/validate_review_signoff.py`](../scripts/validate_review_signoff.py) (a CI step and the
WP8.2 `release` gate). A flat single document — **not** a registry/list, **not** in
`SCHEMA_REGISTRY`.

## Shape

```yaml
schema_version: "1.0"
id: signoff-001
review_ref: review-001             # resolves to review.id
code_version: "<run_ledger code_version>"
decision: APPROVED                 # APPROVED | REJECTED
signed_by: "T. Fehr"
date: "2026-06-22"
calibration_status: ILLUSTRATIVE   # UNCALIBRATED | ILLUSTRATIVE
```

## Fields

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | non-empty string |
| `id` | yes | non-empty string |
| `review_ref` | yes | non-empty string; **must equal the `review.id`** → else `unresolved-review-ref` |
| `code_version` | yes | non-empty string; **must equal the scenario `run_ledger.yaml` `code_version`** → else `stale-attestation` |
| `decision` | yes | enum `APPROVED` \| `REJECTED`; a `REJECTED` **blocks release** (`rejected-decision`) |
| `signed_by` | yes | non-empty string (who signed) |
| `date` | yes | ISO-8601 `YYYY-MM-DD` → else `invalid-format` |
| `calibration_status` | yes | enum `UNCALIBRATED` \| `ILLUSTRATIVE` — a **DECLARED** honest posture, **not** executed calibration (which is WP9) |

## Contract

- **The approver declares the calibration posture.** `calibration_status` is the single source of
  truth for the §6 "calibration status" axis of `release`; it is surfaced in the release report
  line so a clean `release` is never mistaken for a calibrated/analytically-valid one
  (CONSTITUTION §3). Real calibration arrives in WP9 and may upgrade the vocabulary.
- **The signoff binds to a reviewed, reproducible snapshot.** `review_ref` ties the approval to a
  specific refuter verdict; `code_version` ties both to the run-ledger snapshot. A `REVISE` review
  or a stale `code_version` means the approval no longer applies. ⚠ **Lockfile discipline**: a
  declared-input change → regenerate the ledger → re-review and **re-sign** (update `code_version`
  here and in `review.yaml`), then re-commit. See [review.schema.md](review.schema.md),
  [run_ledger.schema.md](run_ledger.schema.md), [../docs/RUNBOOK.md](../docs/RUNBOOK.md).

## Error codes

`missing-schema-version`, `missing-field`, `invalid-enum`, `invalid-format`,
`unresolved-review-ref`, `stale-attestation`, `rejected-decision`. Structure first (single-fault),
then resolution/binding/honesty. Fail-closed (exit 2) on a missing / unreadable / empty signoff, or
a broken/absent run-ledger or scenario.

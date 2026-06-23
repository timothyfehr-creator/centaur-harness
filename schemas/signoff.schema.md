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
attestation_kind: INDEPENDENT      # INDEPENDENT | SYNTHETIC_SELF_CHECK
decision: APPROVED                 # INDEPENDENT: APPROVED|REJECTED ; SYNTHETIC_SELF_CHECK: EXTERNAL_REVIEW_PENDING|SELF_CHECK_FAILED
signed_by: "T. Fehr"
date: "2026-06-22"
calibration_status: ILLUSTRATIVE   # UNCALIBRATED | ILLUSTRATIVE | CALIBRATED
calibration_disposition: NOT_FEASIBLE          # NONE | NOT_FEASIBLE | INSUFFICIENT_DATA | CALIBRATED
calibration_feasibility_ref: calfeas-001       # required iff disposition is a feasibility verdict
calibration_feasibility_sha256: "<64 hex>"     # binds the calibration_feasibility.yaml bytes
```

## Fields

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | non-empty string |
| `id` | yes | non-empty string |
| `review_ref` | yes | non-empty string; **must equal the `review.id`** → else `unresolved-review-ref` |
| `code_version` | yes | non-empty string; **must equal the scenario `run_ledger.yaml` `code_version`** → else `stale-attestation` |
| `attestation_kind` | yes | enum `INDEPENDENT` \| `SYNTHETIC_SELF_CHECK`. PARTITIONS the legal `decision`: a `SYNTHETIC_SELF_CHECK` (the harness checking its OWN work) cannot spell `APPROVED`. Must equal `review.attestation_kind` → else `kind-mismatch`; an INDEPENDENT kind whose `signed_by` is not in the human-controlled independent-reviewer allow-list (`attestation_reviewers.yaml`) → `unlisted-independent-reviewer` |
| `decision` | yes | enum `APPROVED` \| `REJECTED` \| `EXTERNAL_REVIEW_PENDING` \| `SELF_CHECK_FAILED`, **legal by kind** (INDEPENDENT ⇒ APPROVED/REJECTED; SYNTHETIC_SELF_CHECK ⇒ EXTERNAL_REVIEW_PENDING/SELF_CHECK_FAILED) → else `kind-decision-mismatch`. A `REJECTED`/`SELF_CHECK_FAILED` **blocks release** (`rejected-decision`/`self-check-failed`) |
| `signed_by` | yes | non-empty string (who signed) |
| `date` | yes | ISO-8601 `YYYY-MM-DD` → else `invalid-format` |
| `calibration_status` | yes | enum `UNCALIBRATED` \| `ILLUSTRATIVE` \| `CALIBRATED` — a **DECLARED** posture; **CALIBRATED requires a resolving `calibration.yaml`** record (WP9, [calibration.schema.md](calibration.schema.md)), the other two need none |
| `calibration_disposition` | yes | enum `NONE` \| `NOT_FEASIBLE` \| `INSUFFICIENT_DATA` \| `CALIBRATED` (WP-E2c.1 #2) — the **DECLARED** calibration disposition. A feasibility verdict (`NOT_FEASIBLE`/`INSUFFICIENT_DATA`) **obliges** a bound `calibration_feasibility.yaml` (cross-checked by [validate_calibration_feasibility.py](../scripts/validate_calibration_feasibility.py)); `NONE`/`CALIBRATED` must carry no record |
| `calibration_feasibility_ref` | iff feasibility verdict | non-empty string; **must equal the feasibility record's `id`** → else `unresolved-feasibility-ref` (in the feasibility gate); absent under a feasibility disposition → `missing-field` |
| `calibration_feasibility_sha256` | iff feasibility verdict | 64 lowercase hex; **must equal `sha256(calibration_feasibility.yaml)`** → else `stale-feasibility-binding` (in the feasibility gate); a non-64-hex value → `invalid-format`. Editing the record without re-signing this hash fails release |

## Contract

- **A synthetic self-check can never read as an independent attestation (WP-E2c.1).**
  `attestation_kind: SYNTHETIC_SELF_CHECK` (the loop/harness checking its own work) admits only
  `EXTERNAL_REVIEW_PENDING` / `SELF_CHECK_FAILED` — `APPROVED` is structurally unreachable — and `release`
  reports `SELF-VERIFIED; NOT INDEPENDENTLY ATTESTED`. Only an `INDEPENDENT` signoff (a human / genuinely
  independent reviewer signing the artifact) yields `complete and INDEPENDENTLY attested`. The disclaimer is
  a parsed enum, not a YAML comment (comments evaporate on load).
- **Independence is allow-listed, not self-declared.** `attestation_kind: INDEPENDENT` is honored only when
  `signed_by` appears verbatim in the repo's human-controlled `attestation_reviewers.yaml`
  (`independent_reviewers`). The list starts **empty**, so a self-declared `INDEPENDENT` label on a synthetic
  signer cannot mint its own independence (`unlisted-independent-reviewer`); a human adding a reviewer there
  is a conspicuous, merge-reviewable act. A regex on the signer name is a heuristic, not the boundary.
- **The approver declares the calibration posture.** `calibration_status` is the single source of
  truth for the §6 "calibration status" axis of `release`; it is surfaced in the release report
  line so a clean `release` is never mistaken for a calibrated/analytically-valid one
  (CONSTITUTION §3). A `CALIBRATED` posture is evidence-or-label (§5): it must resolve to a
  `calibration.yaml` record (WP9, `validate_calibration.py`); `UNCALIBRATED`/`ILLUSTRATIVE` need none.
- **The approver declares the calibration DISPOSITION, and it cannot just "say so" (WP-E2c.1 #2).**
  `calibration_disposition` records whether calibration was `NONE` (not attempted), `NOT_FEASIBLE` /
  `INSUFFICIENT_DATA` (attempted, cannot), or `CALIBRATED`. A feasibility verdict **obliges a bound record**:
  `calibration_feasibility_ref` + `calibration_feasibility_sha256` pin a `calibration_feasibility.yaml` whose
  id and exact bytes must match (cross-checked in `validate_calibration_feasibility.py`). So deleting the
  record (`missing-feasibility-record`) or editing it without re-signing the hash (`stale-feasibility-binding`)
  fails release — the disposition is enforced, not voluntary.
- **The signoff binds to a reviewed, reproducible snapshot.** `review_ref` ties the approval to a
  specific refuter verdict; `code_version` ties both to the run-ledger snapshot. A `REVISE` review
  or a stale `code_version` means the approval no longer applies. ⚠ **Lockfile discipline**: a
  declared-input change → regenerate the ledger → re-review and **re-sign** (update `code_version`
  here and in `review.yaml`), then re-commit. See [review.schema.md](review.schema.md),
  [run_ledger.schema.md](run_ledger.schema.md), [../docs/RUNBOOK.md](../docs/RUNBOOK.md).

## Error codes

`missing-schema-version`, `missing-field`, `invalid-enum`, `invalid-format`,
`unresolved-review-ref`, `stale-attestation`, `rejected-decision`, `kind-mismatch`,
`kind-decision-mismatch`, `self-check-failed`, `unlisted-independent-reviewer`. Structure first (single-fault),
then resolution/binding/honesty. Fail-closed (exit 2) on a missing / unreadable / empty signoff, or
a broken/absent run-ledger or scenario.

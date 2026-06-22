# Review schema (v1) — the refuter attestation (WP8.1)

Contract for a per-scenario **review** artifact
(`examples/<scenario>/review.yaml`): a lightweight record that an adversarial **refuter**
examined the scenario package and returned a verdict. Enforced by
[`scripts/validate_review_signoff.py`](../scripts/validate_review_signoff.py) (a CI step and the
WP8.2 `release` gate). A flat single document — **not** a registry/list, **not** in
`SCHEMA_REGISTRY` (so `scaffold` never requires it).

## Shape

```yaml
schema_version: "1.0"
id: review-001
target: ukraine_crimea_logistics   # the scenario this review covers
code_version: "<run_ledger code_version>"
verdict: ACCEPT                    # ACCEPT | REVISE
reviewer: "adversarial-review-panel"
findings: ["...", "..."]           # >= 1 non-empty
as_of_date: "2026-06-22"           # optional
```

## Fields

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | non-empty string |
| `id` | yes | non-empty string; the `signoff.review_ref` resolves to it |
| `target` | yes | non-empty string; **must equal the scenario directory name** → else `unresolved-scenario-ref` |
| `code_version` | yes | non-empty string; **must equal the scenario `run_ledger.yaml` `code_version`** → else `stale-attestation` |
| `verdict` | yes | enum `ACCEPT` \| `REVISE`; a `REVISE` **blocks release** (`revise-verdict`) |
| `reviewer` | yes | non-empty string (who/what refuted) |
| `findings` | yes | a list with **≥ 1** non-empty string → else `empty-findings` |
| `as_of_date` | no | ISO-8601 `YYYY-MM-DD` if present |

## Contract

- **STRUCTURAL + ATTESTATION ONLY.** A review existing with `verdict: ACCEPT` means a refuter
  pass was *recorded*, **not** that the analysis is valid (CONSTITUTION §3).
- **Reproducibility binding (extends WP7).** `code_version` pins the run-ledger snapshot the
  review covers. Because `review.yaml` is **not** a declared input of the run-ledger, committing
  it does not move the ledger SHA — the check is recorded-vs-recorded. When a **declared input**
  drifts and `run_ledger.yaml` is regenerated to a new `code_version`, this review goes **stale**
  and must be re-done. ⚠ **Lockfile discipline:** after
  `validate_run_ledger.py --write`, update `code_version` here (and in `signoff.yaml`) to match,
  then re-commit. See [run_ledger.schema.md](run_ledger.schema.md), [../docs/RUNBOOK.md](../docs/RUNBOOK.md).

## Error codes

`missing-schema-version`, `missing-field`, `invalid-enum`, `empty-findings`,
`unresolved-scenario-ref`, `stale-attestation`, `revise-verdict`. Structure is validated first
(single-fault); resolution/binding/honesty run only on a structurally clean review. Fail-closed
(exit 2) on a missing / unreadable / empty review. See [signoff.schema.md](signoff.schema.md).

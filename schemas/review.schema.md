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
attestation_kind: INDEPENDENT      # INDEPENDENT | SYNTHETIC_SELF_CHECK
verdict: ACCEPT                    # INDEPENDENT: ACCEPT|REVISE ; SYNTHETIC_SELF_CHECK: SELF_CHECK_PASSED|SELF_CHECK_REVISE
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
| `attestation_kind` | yes | enum `INDEPENDENT` \| `SYNTHETIC_SELF_CHECK`. PARTITIONS the legal `verdict`: a `SYNTHETIC_SELF_CHECK` cannot spell `ACCEPT`. Must equal `signoff.attestation_kind` → else `kind-mismatch`; an INDEPENDENT kind whose `reviewer` is not in the human-controlled independent-reviewer allow-list (`attestation_reviewers.yaml`) → `unlisted-independent-reviewer` |
| `verdict` | yes | enum `ACCEPT` \| `REVISE` \| `SELF_CHECK_PASSED` \| `SELF_CHECK_REVISE`, **legal by kind** (INDEPENDENT ⇒ ACCEPT/REVISE; SYNTHETIC_SELF_CHECK ⇒ SELF_CHECK_PASSED/SELF_CHECK_REVISE) → else `kind-verdict-mismatch`. A `REVISE`/`SELF_CHECK_REVISE` **blocks release** (`revise-verdict`/`self-check-revise`) |
| `reviewer` | yes | non-empty string (who/what refuted) |
| `findings` | yes | a list with **≥ 1** non-empty string → else `empty-findings` |
| `as_of_date` | no | ISO-8601 `YYYY-MM-DD` if present |

## Contract

- **STRUCTURAL + ATTESTATION ONLY.** A review existing with `verdict: ACCEPT` means a refuter
  pass was *recorded*, **not** that the analysis is valid (CONSTITUTION §3).
- **A synthetic self-check is not an independent refuter pass (WP-E2c.1).** `attestation_kind:
  SYNTHETIC_SELF_CHECK` admits only `SELF_CHECK_PASSED` / `SELF_CHECK_REVISE` — it cannot spell `ACCEPT`,
  so the loop's own check can never be mistaken for an independent refuter accept. The kind must agree with
  the signoff's.
- **Independence is allow-listed, not self-declared.** `attestation_kind: INDEPENDENT` is honored only when
  `reviewer` appears verbatim in the repo's human-controlled `attestation_reviewers.yaml`
  (`independent_reviewers`). The list starts **empty**, so until a human adds a genuinely-independent reviewer
  nothing is INDEPENDENT — a self-declared `INDEPENDENT` label cannot mint its own independence
  (`unlisted-independent-reviewer`). A regex on the signer name is a heuristic, not a boundary; the allow-list
  is the boundary.
- **Reproducibility binding (extends WP7).** `code_version` pins the run-ledger snapshot the
  review covers. Because `review.yaml` is **not** a declared input of the run-ledger, committing
  it does not move the ledger SHA — the check is recorded-vs-recorded. When a **declared input**
  drifts and `run_ledger.yaml` is regenerated to a new `code_version`, this review goes **stale**
  and must be re-done. ⚠ **Lockfile discipline:** after
  `validate_run_ledger.py --write`, update `code_version` here (and in `signoff.yaml`) to match,
  then re-commit. See [run_ledger.schema.md](run_ledger.schema.md), [../docs/RUNBOOK.md](../docs/RUNBOOK.md).

## Error codes

`missing-schema-version`, `missing-field`, `invalid-enum`, `empty-findings`,
`unresolved-scenario-ref`, `stale-attestation`, `revise-verdict`, `kind-mismatch`,
`kind-verdict-mismatch`, `self-check-revise`, `unlisted-independent-reviewer`. Structure is validated first
(single-fault); resolution/binding/honesty run only on a structurally clean review. Fail-closed
(exit 2) on a missing / unreadable / empty review. See [signoff.schema.md](signoff.schema.md).

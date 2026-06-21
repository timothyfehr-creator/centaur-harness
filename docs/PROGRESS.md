# Progress Ledger

Cross-work-package status for the Centaur harness — one short entry per work
package. See [IMPLEMENTATION_PLAN_V2.md](../IMPLEMENTATION_PLAN_V2.md) for the
canonical plan and ordering.

## WP-1 — Bootstrap scaffold ✅ complete (commit `beb3daf`)

Created the smallest viable repo so verification could run: `scripts/verify.py`,
`tests/test_verify_modes.py`, `.github/workflows/ci.yml`, `.gitignore`,
`README.md`, `AGENTS.md`, `CLAUDE.md`, `docs/CONSTITUTION.md`,
`docs/COMMAND_SAFETY.md`.

## WP0.1 — Scaffold verification & CI ✅ complete

WP0.1's behavior was already delivered by the WP-1 bootstrap; this pass hardened
the tests, added this ledger, and ran CI for real.

| Acceptance criterion | Status |
|---|---|
| `python scripts/verify.py --mode scaffold` exits 0 | ✅ |
| `python scripts/verify.py` exits 0, defaults to scaffold | ✅ |
| unknown modes exit nonzero with a clear error | ✅ (exit 2, `unknown mode`) |
| `pytest` exits 0 | ✅ (5 passed) |
| CI runs scaffold-verify + pytest | ✅ (see run below) |
| existing checks preserved | ✅ |

- Tests hardened in commit `d349421` (draft/release assert the clear `unknown
  mode` error; scaffold asserts its `scaffold verification OK` success message).
- **GitHub Actions:** ✅ success — run
  [27730539855](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27730539855)
  on `924d260` (steps *Scaffold verification* and *Tests* both passed).
- Note: the local machine has `python3` (3.14) but no `python` binary; tests
  invoke via `sys.executable`, and CI provisions `python` via
  `actions/setup-python`.

## WP0.2 — Command safety & secret scan ✅ complete

Implemented `scripts/secret_scan.py` (a minimum gate, not an oracle), wired it into
CI, and flipped the command-safety docs from deferred to implemented.

| Acceptance criterion | Status |
|---|---|
| bare `python scripts/secret_scan.py` exits 0 | ✅ (13 files at WP0.2, grows with the repo; fail-closed if git fails / 0 files) |
| safe fixture exits 0 | ✅ |
| unsafe fixture exits 1 (fake secret caught) | ✅ (masked, names the file) |
| `pytest` exits 0 | ✅ (30 passed) |
| CI runs the secret scan | ✅ (step before scaffold + tests) |
| no broad framework / new dependency added | ✅ (pure stdlib) |

- Scanner + fixtures + tests: `eae1595`; CI wiring + docs + tracked fixtures:
  `553f98a`; hardening per adversarial review (fail-closed, delimited-token
  placeholders, per-rule recall, UUID precision): `cbbe2c8`.
- CI action versions bumped to `checkout@v5` / `setup-python@v6` (Node-20
  deprecation warning cleared).
- **GitHub Actions:** ✅ success — run
  [27731991363](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27731991363)
  on `cbbe2c8` (Secret scan, Scaffold verification, Tests all passed).
- Note: fixture/test secrets are synthetic and prefix-split so GitHub push
  protection does not block the push.

## WP1.1 — Enforceable scenario schema ✅ complete

Made scenario YAML machine-validatable (structural only; sourcing is WP2.3). Chose
**PyYAML + a hand-rolled validator** (one new dependency: PyYAML) over
jsonschema/pydantic — the cross-field rules need custom code regardless.

| Acceptance criterion | Status |
|---|---|
| valid fixtures + the real example pass | ✅ |
| each invalid fixture fails for its EXACT reason | ✅ (9 codes, one finding each) |
| schema_version / branches / ≥3 signposts / ≥1 falsifier / rationale-or-update / prob sum | ✅ |
| scenario validation wired into scaffold | ✅ (structural; fails closed without PyYAML) |
| `pytest` exits 0 | ✅ (46 passed) |
| existing checks preserved; no out-of-scope work | ✅ |

- Feature commit `ea9973e`: `scripts/validate_schemas.py`,
  `examples/ukraine_crimea_logistics/scenario.yaml` (ILLUSTRATIVE/unsourced),
  `schemas/scenario.schema.md`, valid/invalid fixtures + `tests/test_schema_validation.py`,
  scaffold hook in `verify.py`, `requirements-dev.txt` (pytest + PyYAML), CI step.
- **GitHub Actions:** ✅ success — run
  [27733665200](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27733665200)
  on `ea9973e` (Install deps, Secret scan, Schema validation, Scaffold verification,
  Tests all passed).
- Deferred within WP1.1 (flagged): `label`/`as_of_date` enforcement (WP3.2 / §6);
  tighter probability tolerance (backlog); other schemas (WP1.2). PyYAML is now a
  required dependency — scaffold **fails closed** without it.

## WP1.2 — Core schema skeletons ✅ complete

Generalized the validator to be **kind-aware** (agent / source / claim / event / turn)
while leaving the scenario validator and the scaffold/CI wiring byte-for-byte
unchanged. Flat declarative skeleton specs + a registry; one PROVISIONAL enum per kind
where natural, grounded in STANAG 2511 / ICD-203 + Kent / DIME / IR typology.

| Acceptance criterion | Status |
|---|---|
| schemas exist + enforceable (5 kinds) | ✅ (`--kind`; flat declarative specs) |
| missing required fields fail | ✅ (`missing-schema-version` / `missing-field`) |
| invalid enum values fail | ✅ (`invalid-enum`; absent enum ⇒ `missing-field`) |
| wrong types fail | ✅ (`wrong-type`; e.g. `turn.number`) |
| valid fixtures pass | ✅ (5 valid + 13 single-fault invalid) |
| scaffold / CI stay green; no out-of-scope semantics | ✅ |
| `pytest` exits 0 | ✅ (64 passed) |

- Feature commit `dc9bb10`: `scripts/validate_schemas.py` (kind-aware),
  `schemas/{agent,source,claim,event,turn}.schema.md`, 18 synthetic fixtures +
  parametrized tests. `verify.py`, `.github/workflows/ci.yml`, `requirements-dev.txt`
  unchanged.
- **GitHub Actions:** ✅ success — run
  [27735538268](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27735538268)
  on `dc9bb10` (Secret scan, Schema validation, Scaffold verification, Tests passed).
- Notes / deferred: enum **semantics** deferred (claim↔source resolution WP2.1, event
  semantics WP2.2, agent grounding WP5, turn ordering/replay WP7); enum values are
  PROVISIONAL. **No real instances** added — skeleton CI coverage rides on the `pytest`
  step, not the bare schema-validation step. Backlog: canonical filenames are plural
  (`agents.yaml`); a singular `agent.yaml` would currently infer scenario — harden when
  real instances land.

## WP2.1 — Source & claim registry validation ✅ complete

The first **evidence gate**: `factbase/sources.yaml` + `factbase/claims.yaml`, with
claim→source resolution and a source-tier rule. Two standalone validators reuse the
WP1.2 skeleton engine via a derived entry-spec; **scaffold/`verify.py` untouched**
(resolution is draft-mode/WP4 territory per CONSTITUTION §3).

| Acceptance criterion | Status |
|---|---|
| source + claim registries exist + validate clean | ✅ (illustrative/synthetic) |
| a valid claim resolves to a valid source | ✅ |
| missing / unresolved source ref fails | ✅ (`missing-source-ref` / `unresolved-source-ref`) |
| missing claim id fails | ✅ (`missing-field`) |
| social-only top-confidence claim fails | ✅ (`confidence-tier-violation`) |
| scaffold + the 64 prior tests stay green; no ingestion | ✅ |
| `pytest` exits 0 | ✅ (82 passed) |

- **Vocab finalized** (user choice): `claim.confidence` = `CONFIRMED / LIKELY /
  UNCERTAIN / UNASSESSED` (intel evidential status). "CONFIRMED" in the plan == the
  implemented top-confidence value; the tier rule triggers on it.
- **Tier rule** = a `CONFIRMED` claim must cite ≥1 source of a **recognized non-SOCIAL
  tier** (OFFICIAL/MAINSTREAM) — fail-closed against missing/unknown tiers (review fix).
- Feature commit `a94d358`: `scripts/validate_sources.py`, `scripts/validate_claims.py`,
  `factbase/*.yaml` (synthetic), 13 registry fixtures + two test files, the
  `CLAIM_SPEC` enum migration, two CI steps.
- **GitHub Actions:** ✅ success — run
  [27843062841](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27843062841)
  on `a94d358` (Secret scan, Schema validation, Source/Claim registry validation,
  Scaffold verification, Tests all passed).
- **Deferred (named):** the §5 "label unsupported items ASSUMPTION/MODEL_OUTPUT/
  ILLUSTRATIVE" half is **not** enforced here — WP2.1 requires every *registry* claim
  to resolve; labeling unsourced *narrative* claims is WP3.2/WP4. `as_of_date` is
  accepted-but-unvalidated. Real sourcing of the scenario is WP2.3.

## WP2.2 — Event ledger validation ✅ complete

Extended the evidence chain: an `factbase/events.yaml` ledger where **events reference
claims** (resolution by claim-id, mirroring claims→sources). `validate_events.py` is a
structural twin of `validate_claims.py` minus the tier rule; `verify.py`/scaffold and
`validate_sources`/`validate_claims` untouched.

| Acceptance criterion | Status |
|---|---|
| event ledger exists + validates clean | ✅ (illustrative/synthetic) |
| a valid event resolves to claims | ✅ |
| missing / unresolved claim ref fails | ✅ (`missing-claim-ref` / `unresolved-claim-ref`) |
| event confidence + category validate | ✅ (`invalid-enum`; `confidence` reuses the claim vocab) |
| duplicate id fails | ✅ (`duplicate-id`) |
| 82 prior tests stay green; no ingestion | ✅ |
| `pytest` exits 0 | ✅ (94 passed) |

- **Vocab:** `event.confidence` = `CONFIRMED / LIKELY / UNCERTAIN / UNASSESSED` (reuses
  the claim vocab — user choice). **No confidence-consistency cross-rule** and no dead
  code for one (minimal — user choice).
- Feature commit `9f61447` (atomic): `scripts/validate_events.py`, `factbase/events.yaml`
  (synthetic), the `EVENT_SPEC` confidence migration + the 3 schema event fixtures +
  `event_invalid_confidence`, 8 registry fixtures + `tests/test_event_validation.py`, one
  CI step.
- **GitHub Actions:** ✅ success — run
  [27882984163](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27882984163)
  on `9f61447` (Secret scan, Schema validation, Source/Claim/Event registry validation,
  Scaffold verification, Tests all passed).
- **Deliberate invariant (flagged):** every event references ≥1 claim regardless of
  confidence — a likely future-relaxation point for raw/unsourced events. Note: factbase
  registry *structure* is enforced in CI by the resolution validators (each re-runs the
  skeleton on entries), not by the scenario-only bare `validate_schemas.py` step.

## WP2.3 — Source-or-label the Ukraine example ✅ complete (Phase 2 done)

The honesty capstone of Phase 2: scenario **state items** carry a CONSTITUTION-§4
world-vs-game label, and `validate_state.py` enforces the §5 rule — a
`REAL_WORLD_BASELINE` item must cite ≥1 claim that resolves to the factbase, or be
relabeled. Closes the §5 "label-unsupported-items" half deferred since WP2.1.

| Acceptance criterion | Status |
|---|---|
| the example state validates clean, asserts no real-world fact | ✅ (all ASSUMPTION/ILLUSTRATIVE) |
| a REAL_WORLD_BASELINE item w/o a resolving claim fails | ✅ (`unsupported-baseline` / `unresolved-claim-ref`) |
| an unlabeled / bad-label item fails | ✅ (`missing-field` / `invalid-enum`) |
| an ASSUMPTION item with no claims passes | ✅ (non-over-block) |
| 94 prior tests stay green; no out-of-scope work | ✅ |
| `pytest` exits 0 | ✅ (105 passed) |

- **Decisions (user):** state sourcing triggers on the `REAL_WORLD_BASELINE` **label**
  only — claim confidence (CONFIRMED/LIKELY) is enforced on claims by `validate_claims`,
  so **`IMPLEMENTATION_PLAN_V2.md` line 290 was amended**. The shipped example is
  **all-illustrative** (no REAL_WORLD_BASELINE); that resolution path lives in fixtures.
- **Design:** §4 labels = a shared `WORLD_VS_GAME_LABELS` constant (reused by WP3.2); state
  is registry-only and **not** in `SCHEMA_REGISTRY` (avoids a `--kind state` footgun).
  Resolution-only safety relies on CI ordering (`validate_claims` before `validate_state`).
- Feature commit `d2edfca`: `scripts/validate_state.py`, `examples/.../initial_state.yaml`,
  7 registry fixtures + `tests/test_state_validation.py`, `schemas/state.schema.md`, the
  `WORLD_VS_GAME_LABELS` constant, one CI step, the plan amendment.
- **GitHub Actions:** ✅ success — run
  [27884276611](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27884276611)
  on `d2edfca` (Secret scan, Schema validation, Source/Claim/Event registry validation,
  **State validation**, Scaffold verification, Tests all passed).
- Deferred: `as_of_date` accepted-but-unvalidated; a `_registry_id_set(doc, key)` extraction
  (the `_source_index`/`_claim_id_set` duplication) is a candidate future cleanup, not done here.

## WP3.1 — Safety checker ✅ complete (Phase 3 started)

The first Phase 3 gate: `scripts/safety_check.py` + `checks/safety_patterns.yaml` turn
CONSTITUTION §7 into an executable **minimum content gate**. It blocks actionable
operational harm-instructions (weapons/CBRN/explosive construction & synthesis,
step-by-step mass-casualty how-to) while passing strategic assessment. A near-twin of
`secret_scan.py`: `git ls-files` default scan, masked findings, fail-closed exit 0/1/2.

| Acceptance criterion | Status |
|---|---|
| unsafe fixtures fail | ✅ (5 conservative categories, one finding each, masked) |
| safe strategic/logistics fixtures pass | ✅ (force levels, depots, modeled strike, casualty-outcome) |
| the whole repo scans clean | ✅ (`safety check OK (101 files)`) |
| fail-closed on bad/empty/unknown-tier patterns | ✅ (exit 2; 17 failure modes verified in review) |
| findings redacted; honesty invariant machine-checked | ✅ (`_mask`; `test_unsafe_fixtures_contain_no_concrete_procedure`) |
| 105 prior tests stay green; no out-of-scope work | ✅ |
| `pytest` exits 0 | ✅ (129 passed) |

- **Decision (user):** the safe/unsafe line is **conservative** — flag only
  construction/synthesis + explicit step-by-step mass-casualty how-to; do NOT flag
  strategic military discussion (a modeled strike as a scenario event passes). Design =
  two-token co-occurrence (a harm verb + a weapon/agent object on one physical line).
- **Tiers:** a second `broader` tier (operational targeting / strike-execution) ships
  **defined but disabled** (`enabled_tiers: [conservative]`; `CENTAUR_SAFETY_PATTERNS`
  override) — inert data-as-config, settled as not-overbuild in adversarial review.
- **Scope reconciliation (plan amended):** Phase 3's acceptance also lists "unlabeled
  draft artifacts fail" (WP3.2, output-label enforcement) and "draft verification invokes
  safety checks" (WP4, draft-mode wiring). WP3.1 delivers the **unsafe-content** half only
  — a standalone CI step; `verify.py`/scaffold and all `validate_*.py` untouched.
- **Review:** ACCEPT (zero true blockers); folded in a hardened fixture-honesty deny-list
  (rejects procedure/method hints) and simplified the unsafe fixtures to bare triggers.
- Feature commit `e86b988`: `scripts/safety_check.py`, `checks/safety_patterns.yaml`,
  9 safety fixtures + `tests/test_safety_check.py`, `docs/SAFETY_AND_SCOPE.md`, the CI step,
  the plan annotation.
- **GitHub Actions:** ✅ success — run
  [27886573998](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27886573998)
  on `e86b988` (Secret scan, Schema validation, Source/Claim/Event registry validation,
  State validation, **Safety check**, Scaffold verification, Tests all passed).
- Deferred (named): non-digit step numerals / comma-free markers and other paraphrases are
  accepted minimum-gate false negatives (the gate is line-local; documented in
  `SAFETY_AND_SCOPE.md`). The `broader` tier is off by default.
- **Post-WP3.1 audit pass** (a 4-finder workflow confirmed the gate production-ready —
  ReDoS-safe, fail-closed on all config-failure modes, masking/encoding sound):
  docs-accuracy fixes (`bd362f6`) correcting a stale README/CLAUDE gate inventory + adding
  honesty limits (ASCII/homoglyph-blind, synthetic fixtures) and AGENTS parity for the
  `pragma: allowlist safety` marker + `CENTAUR_SAFETY_PATTERNS`; and a hardening commit
  (`0e6e22d`) adding a duplicate-rule-id fail-closed guard and the missing
  `operational_strike_sequencing` broader fixture. **Now 132 tests.** Backlog (unchanged,
  deferred): the `_registry_id_set` extraction and the plural-filename footgun.

## WP3.2 — Output-label validation ✅ complete (Phase 3 done)

The §4 capstone of Phase 3: the scenario top-level `label` is now a **required enum**
constrained to the shared `WORLD_VS_GAME_LABELS` constant (the same vocab `validate_state`
enforces on state items). A ~6-line check in `validate_schemas.py`'s `validate_doc` —
enforced everywhere it runs (the bare CI step **and** `scaffold`). Closes the WP1.1 `label`
deferral and delivers the Phase 3 acceptance line "unlabeled draft artifacts fail".

| Acceptance criterion | Status |
|---|---|
| an unlabeled scenario fails | ✅ (`missing-field`, one finding) |
| a label outside the vocab fails | ✅ (`invalid-enum`, one finding) |
| the example + all valid fixtures pass | ✅ (incl. `scenario_labeled` = `GAMED_FUTURE`) |
| every migrated invalid fixture stays single-fault | ✅ (8 scenario invalids + 2 new) |
| scaffold + CI enforce it; 132 prior tests green | ✅ |
| `pytest` exits 0 | ✅ (135 passed) |

- **Decisions (user):** scenario **top-level label only** (not per-branch); enforced
  **always-on in `validate_schemas.py`** (CI + scaffold), not draft-only — §3 favors this
  (an unlabeled scenario must not falsely pass scaffold; draft-only would leave that hole
  until WP4). No new gate.
- **SSOT:** reuses the existing `WORLD_VS_GAME_LABELS` tuple (no copy); `if/elif` ⇒
  single-fault, reusing the `missing-field` / `invalid-enum` codes.
- **Migration (load-bearing):** added `label: ILLUSTRATIVE` to 3 valid + 8 scenario-path
  invalid fixtures so each keeps its sole intended fault; `malformed_yaml` exempt (dies at
  parse); the `--kind` skeleton fixtures are unaffected (they use `_validate_skeleton`).
- **Review:** ACCEPT (zero blockers); adversarial label inputs (empty/whitespace/list/
  number/null/wrong-case) all behave correctly.
- Feature commit `df0cc3d`: the `validate_doc` label check, 3 new + 11 migrated fixtures,
  `tests/test_schema_validation.py`, `schemas/scenario.schema.md`, the plan reconciliation.
- **GitHub Actions:** ✅ success — run
  [27887933991](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27887933991)
  on `df0cc3d` (Secret scan, **Schema validation**, Source/Claim/Event/State validation,
  Safety check, **Scaffold verification**, Tests all passed).
- Out of scope (deferred): `as_of_date` (Constitution §6, not §4); per-branch labels;
  draft-mode wiring (WP4).

## Deferred (not started)

Structural draft mode (WP4.1 — composes the schema/source/state/safety/label gates into
`verify.py --mode draft`), release mode (WP8.2), and engine work.

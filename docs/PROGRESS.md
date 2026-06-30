# Progress Ledger

> **Internal build ledger** — a dense, per-work-package working record. For the project
> overview, **start with the [README](../README.md)**.

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

## WP4 — Structural draft verification mode ✅ complete (Phase 4 done)

The first **composed** gate: `verify.py --mode draft` reuses `verify_scaffold` in-process
(repo integrity + scenario schema) then **subprocesses** the source/claim/event/state/
safety gate CLIs and aggregates exit codes — a self-contained superset that fully answers
"is this a valid draft?". Per CONSTITUTION §3 it reports active `[PASS]`/`[FAIL]` checks
**and** a `[SKIP]` list of not-yet-implemented ones, and its success line is **STRUCTURAL
ONLY** — never an analytical-validity claim. Delivers the open Phase 3 line "draft
verification invokes safety checks".

| Acceptance criterion | Status |
|---|---|
| scaffold stays repo-level + lightweight | ✅ (behavior unchanged) |
| draft reports active AND not-yet-implemented checks | ✅ (`[PASS]/[FAIL]` + `[SKIP]` block) |
| draft fails on any schema/evidence/safety/label failure | ✅ (rc 1/2/launch-error/timeout → draft exit 1) |
| release cannot falsely pass | ✅ (exit 2, distinct "unavailable" message) |
| 135 prior tests stay green | ✅ |
| `pytest` exits 0 | ✅ (139 passed) |

- **Decisions (user):** **subprocess** each gate CLI (CI-faithful, decoupled, fail-closed
  inherited) + a **self-contained superset** (one command answers the whole question).
- **Never false-passes:** `exit 0` iff every active check passes; `_run_gate` is hardened
  with `timeout=120` + `try/except (OSError, SubprocessError)` → a gate that can't run is a
  fail-closed FAIL, not a silent skip. `verify.py` is excluded from `DRAFT_GATES` (no
  self-recursion; guard-tested).
- **`agents validate structurally`** is reported **NOT-YET-ACTIVE** (`[SKIP]`; no real
  `agents.yaml` until WP5), not silently dropped.
- **CI:** **adds** a "Draft verification" step after Scaffold and **keeps** the standalone
  scaffold + 6 gate steps — draft inherits `safety_check`'s `git ls-files` dependency that
  scaffold lacks, so the git-independent scaffold signal is preserved (honest fail-closed on
  no-git).
- **Review:** ACCEPT (zero blockers); the failure-path tests are **in-process** monkeypatch
  (no repo mutation / no git-tmp-copy), honoring the concurrent-session rule.
- Feature commit `9c7d911`: `scripts/verify.py` (`verify_draft`/`_run_gate`/report),
  `tests/test_verify_modes.py`, the CI Draft step, `CLAUDE.md`, the plan reconciliation.
- **GitHub Actions:** ✅ success — run
  [27888510542](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27888510542)
  on `9c7d911` (Secret scan, Schema/Source/Claim/Event/State validation, Safety check,
  Scaffold verification, **Draft verification**, Tests all passed).
- Out of scope (deferred): no new gates, no analytical/agent-grounding (WP5),
  refuter/calibration/replay/signoff, no draft-takes-a-scenario-path arg.

## WP5.1 — Minimal agent grounding ✅ complete (Phase 5 done)

`scripts/validate_agents.py` makes agents grounded, not generic chatbots: each agent must
cite a resolving **knowledge book** AND a **capability** resolving to a claim/assumption. It
is the first WP to light up a `[SKIP]` line in draft — `agent grounding` is now a live
`[PASS]`. Mirrors `validate_state`; introduces the `agents.yaml` registry, a compact knowledge
catalog, and `factbase/assumptions.yaml`.

| Acceptance criterion | Status |
|---|---|
| each agent has knowledge references | ✅ (≥1 resolving book; else `ungrounded-agent`) |
| capability constraints resolve to claims OR assumptions | ✅ (union; `unresolved-capability-ref`) |
| behavioral assumptions resolve to assumption ids | ✅ (assumptions only; `unresolved-assumption-ref`) |
| ungrounded generic agents fail | ✅ (`ungrounded-agent` — knowledge AND ≥1 resolving capability) |
| draft can't use ungrounded agents; the `[SKIP]` is now `[PASS]` | ✅ (`validate_agents` joined `DRAFT_GATES`) |
| 139 prior tests green | ✅ |
| `pytest` exits 0 | ✅ (155 passed) |

- **Decisions (user):** compact **resolution-only** knowledge books
  (`knowledge/{country,institution}_books/`, `{id,title,summary}`); `factbase/assumptions.yaml`
  validated **folded** into `validate_agents` (no separate gate); grounding bar = **knowledge
  AND ≥1 resolving capability** (the anti-"citation-wearing roleplayer" bar).
- **§4:** `assumptions.yaml` is mono-label by location (the registry embodies `ASSUMPTION`);
  no per-entry label/confidence/sources. Capability refs resolve to claims∪assumptions;
  behavioral refs to assumptions only.
- **Fail-closed (exit 2):** any missing/empty/non-mapping upstream (claims, assumptions,
  agents) or a bad/idless knowledge book / empty knowledge dir. Single-fault fixtures: each
  invalid agent is otherwise-grounded with one defect (empty `refs` avoids the bar /
  unresolved-ref double-fire).
- **Review:** ACCEPT (zero blockers); folded two doc/test nits (the draft test now asserts
  the active `[PASS] agent grounding` + a still-`[SKIP]` check; knowledge-book `schema_version`
  is documented as convention-not-enforced).
- Feature commit `ef0395a`: `scripts/validate_agents.py`, the example agents.yaml +
  assumptions.yaml + 2 knowledge books, `tests/test_agent_validation.py` + 13 fixtures, the
  `verify.py` wiring, the CI step, `schemas/agent.schema.md` rewrite + 2 new schema docs, the
  plan reconciliation.
- **GitHub Actions:** ✅ success — run
  [27889520943](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27889520943)
  on `ef0395a` (Secret scan, Schema/Source/Claim/Event/State validation, **Agent grounding
  validation**, Safety check, Scaffold verification, **Draft verification**, Tests all passed).
- Out of scope (deferred): encyclopedic / sourced-fact books, doctrine libraries, retrieval,
  fog-of-war (WP6), numeric capability modeling.

## WP6 — Fog-of-war skeleton ✅ complete (Phase 6 done)

The first per-agent information partition: each agent's compiled context = public state +
*only* its own private state; the adjudicator sees all; nothing else leaks. Adds the first
`core/` module (`context_compiler.py`) — a pure deterministic library, **not** a `draft`
gate — proven by leak tests. Delivered as two commits (WP6.1 partition data, WP6.2 compiler).

| Acceptance criterion | Status |
|---|---|
| each agent gets public + its permitted private state | ✅ (`compile_context`) |
| unauthorized private fields do not appear in any context | ✅ (negative leak tests; cross-agent + adjudicator-only) |
| adjudicator visibility is explicit | ✅ (enumerated "sees all" branch + a real `adjudicator.yaml`) |
| no full game engine required | ✅ (a static, deterministic, RNG-free compiler) |
| 157 prior tests stay green | ✅ |
| `pytest tests/test_context_compiler.py` + `pytest` | ✅ (177 passed) |

- **Decisions (user):** partition = **file-per-agent** (`examples/<scenario>/state/public.yaml`
  + `private/<agent-id>.yaml` + `private/adjudicator.yaml`; visibility = file location, same
  v1 registry schema, no new fields); the compiler is a **library, not a draft gate**
  (`verify.py`/`DRAFT_GATES`/CI byte-identical; the exit gate is `pytest`); `initial_state.yaml`
  **untouched** (parallel, additive — no migration).
- **Fail-closed (`FogError`) at load, every path:** an agent named `adjudicator`; missing/unusable
  `public.yaml`; an unusable private file; an **orphan** `private/<id>.yaml` (id not a known
  agent or `adjudicator`); `schema_version` disagreement across files; a non-globally-unique item
  id; empty `items`. **Pure/deterministic:** no RNG/clock/env, items shallow-copied (inputs never
  mutated), fixed order, public's `as_of_date` governs.
- **Review:** ACCEPT (zero blockers) — leakage / fail-closed / determinism / purity empirically
  verified; edge cases (no private file, missing private dir) robust.
- Feature commits `645d4ae` (WP6.1: the `state/` partition + the `state.schema.md` fog section)
  and `30473ea` (WP6.2: `core/context_compiler.py`, `tests/test_context_compiler.py`, 9 fog
  fixtures). Process: also shipped `docs/RUNBOOK.md` (`23865b4`) codifying the WP-delivery cadence.
- **GitHub Actions:** ✅ success — run
  [27963421789](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27963421789)
  on `30473ea` (all gates + Draft verification + Tests passed; the compiler is library-only so
  draft is unchanged).
- Out of scope (deferred): active deception, delayed intelligence, stale BDA, probabilistic
  sensing — hence no per-item `visible_to`, no turn-gated reveal, no RNG, no engine loop.

## WP7 — Reproducibility run-ledger ✅ complete (Phase 7 done)

CONSTITUTION §6: in this pre-engine harness a "run" is the deterministic computation over the
declared input artifacts, so reproducibility means pinning a content hash of every declared
input. Ships a per-scenario `run_ledger.yaml` **lockfile** + a fail-closed **drift gate**
(`validate_run_ledger.py`) that recomputes the live hashes and confirms the committed ledger
still reproduces, with `--write` to regenerate. WP7.1 (structure) and WP7.2 (recompute-and-diff)
are folded into one gate. Also closes the `as_of_date` backlog (validated if present on scenario
+ state). Two feature commits + this ledger.

| Acceptance criterion | Status |
|---|---|
| run artifact format defined + a real example pinned | ✅ (`run_ledger.yaml`, 13 inputs; `schemas/run_ledger.schema.md`) |
| tamper-evident: a changed / added / removed input fails closed | ✅ (`hash-mismatch` / `extra-input` / `missing-input` + a copy-paste regenerate hint) |
| deterministic regeneration | ✅ (`--write` byte-identical, round-trips; pinned `safe_dump`) |
| default check needs no engine and no git | ✅ (raw-bytes content hashes; git only for `--write` provenance) |
| structural faults are single-fault | ✅ (structure-first short-circuit; 5 static fixtures) |
| `as_of_date` validated on scenario + state | ✅ (validate-if-present; strict ISO-8601) |
| 177 prior tests stay green | ✅ (195 passed) |

- **Decisions (user):** hash surface = **declared inputs only** (outputs are pure-derived, so
  the input hash gates them); structure + drift **folded into one** `validate_run_ledger.py`
  (one CI step, **not** in `DRAFT_GATES` — a §6/release-ward axis, orthogonal to §3 structural
  draft); the `as_of_date` ISO retrofit lands on **scenario + state too** (validate-if-present,
  so existing fixtures/dates stay green).
- **Lockfile discipline:** the declared-input set is live globs, so adding / editing / removing
  any `factbase/*.yaml`, `knowledge/**/*.yaml`, `state/private/*.yaml`, or scenario root file
  makes the committed ledger stale → CI drift failure (the intended gate). The failure prints a
  copy-paste `--write` hint; documented in `schemas/run_ledger.schema.md`, `docs/RUNBOOK.md`,
  `CLAUDE.md`. `code_version` is recorded-not-re-derived (a `-dirty` suffix when a declared input
  is uncommitted, scoped to the inputs — not the whole tree). `rng_seeds`/`llm_steps: null` are
  the entire pre-engine forward-compat surface.
- **Review:** ACCEPT — hash/emission determinism, git-independence, fail-closed/integrity, and
  the single-fault short-circuit empirically verified. Folded one blocker: a relative `LEDGER`
  CLI path crashed in `declared_inputs` (`relative_to` against an absolute repo root) instead of
  returning a verdict → resolve `scenario_dir`/`ledger_path` up front; regression-tested.
- Feature commits `92a2f32` (the WP7 gate + `run_ledger.yaml` + schema + 16 tests + the CI step
  + the `verify.py` `[SKIP]` rename + the staleness docs) and `aceefae` (`as_of_date` validated
  on scenario + state, 2 single-fault fixtures).
- **GitHub Actions:** ✅ success — runs
  [27968820887](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27968820887)
  (`92a2f32`) and
  [27969121176](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27969121176)
  (`aceefae`) — all gates + Draft + the new **Run-ledger / reproducibility** step + Tests passed.
- Out of scope (deferred): **turn-replay** (needs the engine — `verify.py` `[SKIP]` reads "turn
  replay (engine run-record; no engine yet)"), RNG seeding, LLM-step capture, GPG/Merkle signing,
  multi-run / history ledgers, env/OS drift tracking.

## WP8 — Review/signoff attestation + release mode ✅ complete (Phase 8 done)

Closes the CONSTITUTION §3 honest-status loop: `release` becomes a real, fail-closed,
**attestation-only** gate. A scenario is releasable only if it carries an adversarial **review**
(refuter verdict) and a human **signoff**, both bound to the reproducible snapshot the run-ledger
pins, with a **declared calibration status**. Two feature commits (WP8.1 the attestation layer,
WP8.2 the release mode) + this ledger.

| Acceptance criterion | Status |
|---|---|
| lightweight review + signoff artifacts defined + a real example | ✅ (`schemas/{review,signoff}.schema.md`; `examples/.../{review,signoff}.yaml`) |
| release fails without sourcing / safety / replay / review / signoff / calibration status | ✅ (`verify_release` composes scaffold + draft gates + run-ledger + the attestation; calibration declared on signoff) |
| release never falsely passes | ✅ (propagates the **worst** gate rc: findings → 1, cannot-run → 2; machine-checked by in-process composition tests) |
| a REVISE review or REJECTED signoff blocks release | ✅ (`revise-verdict` / `rejected-decision`) |
| attestation bound to the reproducible snapshot | ✅ (`code_version` pin → `stale-attestation` on ledger drift) |
| STRUCTURAL + ATTESTATION ONLY, not analytical validity | ✅ (release report disclaimer + the declared calibration in the OK line) |
| 195 prior tests stay green | ✅ (225 passed) |

- **Decisions (user):** honest **declared-status** release (passable now; calibration is a declared
  status, scoring is WP9; turn-replay stays a disclosed `[SKIP]`); **two kinds + a resolving chain
  pinned to the ledger** (`signoff`→`review`→scenario, both pinning the run-ledger `code_version`);
  **both** — built as one long run **and** `release` is a clean unattended/CI-scriptable gate
  (deterministic exit 0/1/2 + a stable final line). Red-team-locked: REVISE+REJECTED both block;
  `calibration_status` on the signoff (single SSOT, no scenario-schema change); single-doc artifacts
  (not lists), **not** in `SCHEMA_REGISTRY`.
- **`validate_review_signoff.py`** (the 11th gate): fail-closed exit 2 on a missing/empty attestation
  or a broken/absent ledger/scenario; structure-first (single-fault) then resolution + binding +
  honesty. Reuses `load_registry` + `_validate_skeleton`/`_valid_iso_date`/`_display`; mirrors
  `validate_state.py`. **Attestation lockfile discipline** (extends WP7): a declared-input change
  regenerates the ledger → attestations go stale → re-review/re-sign (RUNBOOK + CLAUDE + schema docs).
- **`verify.py`:** `release` moves into `VALID_MODES` (`KNOWN_UNAVAILABLE_MODES` removed); `verify_release`
  + `_print_release_report`; `NOT_YET_IMPLEMENTED` shrinks (refuter review + human signoff now run in
  release, like the run-ledger) to turn-replay + calibration scoring. CONSTITUTION §3 release bullet
  rewritten. CI gains `Review/signoff attestation` + `Release verification` steps.
- **Review:** ACCEPT (no blockers) — fail-open / false-pass / single-fault / fail-closed /
  ledger-binding all empirically disproven; the §3 "never falsely passes" invariant stays machine-checked
  by composition (findings → 1, cannot-run → 2, worst-rc-wins) rather than blanket unavailability.
- Feature commits `4e310c4` (WP8.1 attestation layer — resolver + schemas + example + 20 fixtures +
  26 tests + CI step) and `d7ac7ec` (WP8.2 release mode — `verify.py` + the test rewrite + CI step +
  the §3 edit).
- **GitHub Actions:** ✅ success — runs
  [27972909258](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27972909258)
  (`4e310c4`) and
  [27973238425](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27973238425)
  (`d7ac7ec`) — all gates + the new **Review/signoff attestation** + **Release verification** steps + Tests passed.
- Out of scope (deferred): **calibration scoring / backtest** (WP9), the engine (turn-replay), GPG/
  signing, multi-round attestations, a `--json` formatter, governance/approval workflow.

## WP9 — Calibration/backtest marker ✅ complete (Phase 9 done; the plumbing phase is complete)

Applies CONSTITUTION **§5 (evidence or label)** to calibration: a scenario whose signoff declares
`calibration_status: CALIBRATED` must back the claim with a `calibration.yaml` record carrying
proper-scoring-rule provenance; `UNCALIBRATED` / `ILLUSTRATIVE` (the honest "UNCALIBRATED ANALYTICAL
JUDGMENT" label) need none. **The harness RECORDS an externally-computed calibration result; it never
COMPUTES one** (scoring needs the engine + resolved outcomes — a non-goal). One feature commit + this
ledger. **This is the last numbered WP — Phases 0–9 (enforceable plumbing) are complete.**

| Acceptance criterion | Status |
|---|---|
| release outputs declare calibration status or carry the UNCALIBRATED marker | ✅ (3-value `calibration_status`; `CALIBRATED` requires a record, others are honest labels) |
| a CALIBRATED claim must resolve to evidence | ✅ (`unsupported-calibration`, exit 1, blocks release — like §5 `unsupported-baseline`) |
| the record is auditable proper-scoring provenance | ✅ (metric ∈ BRIER/LOG_LOSS/HIT_RATE + in-range value, N>0, outcome authority, ISO scoring date, forecaster) |
| numeric integrity | ✅ (`metric_value`/`baseline_value` reject bool/NaN/Inf + per-metric range; `outcome_count` int N>0) |
| ledger-bound (reproducible snapshot) | ✅ (`stale-calibration` on `code_version` drift) |
| the harness records, never computes calibration | ✅ (no scoring engine; `[SKIP]` calibration *scoring* stays, needs the engine) |
| ukraine lockfile untouched | ✅ (signoff stays ILLUSTRATIVE, no `calibration.yaml`; CALIBRATED path is fixtures-only; guard tests) |
| 225 prior tests stay green | ✅ (252 passed) |

- **Decisions (user):** evidence-or-label record + gate (not a minimal marker) · 3-value
  `calibration_status` (only `CALIBRATED` needs a record) · a **separate** `calibration.yaml` + a
  **new `validate_calibration.py`** (the 12th gate). Red-team-locked: **presence-based** resolution
  (no `calibration_ref`); `metric` ≠ `calibration_status` (separate enums); **3 metrics only**;
  the enum bump + gate + `RELEASE_GATES` + CI ship **atomically** (no fail-open window);
  `ILLUSTRATIVE`+record → `consistency-note`.
- **`validate_calibration.py`:** fail-closed exit 2 on a missing/unreadable signoff/ledger/scenario
  or a present-but-unparseable record; structure-first (single-fault) then resolution; `_is_finite_number`
  rejects bool/NaN/Inf; `METRIC_RANGES` cited (Brier 1950 / GJP). Reuses `_validate_skeleton`/
  `load_registry`; mirrors `validate_review_signoff.py`. **Lockfile discipline** (extends WP7/WP8): a
  declared-input change ⇒ re-`--write` the ledger ⇒ re-score / re-record (`calibration.code_version`).
- **Review:** ACCEPT (no blockers) — false-pass / numeric (bool/NaN/Inf/range) / single-fault /
  fail-closed / ukraine-untouched / scope all empirically disproven.
- Feature commit `6bdb18d` (the gate + record schema + the signoff enum bump + `RELEASE_GATES` + the
  CI step + 20 fixtures + 27 tests + the ukraine guards).
- **GitHub Actions:** ✅ success — run
  [27981038238](https://github.com/timothyfehr-creator/centaur-harness/actions/runs/27981038238)
  (`6bdb18d`) — all gates + the new **Calibration record** + **Release verification** + Tests passed.
- Out of scope (deferred): **calibration scoring / backtest** (needs the engine + outcomes), the
  engine itself (turn-replay), `CUSTOM` metrics, a scoring suite, dashboards.

## Phase E — wargame engine (in progress)

The enforceable-plumbing phase (Phases 0–9) is complete; the wargame **engine** then began **in this
repo** (planning lives separately at `~/Documents/centaur_engine_planning/`). Concise entries — these
landed in focused sessions, not the per-WP CI-run cadence above.

- **WP-E0 — engine contract freeze** ✅ the typed schema docs (`engine_state`, `engine_command`,
  `transition_event`, `turn_record`) + `docs/ENGINE_CONTRACT.md` (keystone turn-record, TOTAL resolution
  table, canon-v1, event-addressed RNG, fog policy, the 12 PASS conditions) + the abstract
  `examples/contested_logistics_abstract/` slice.
- **WP-E1 — durable turn-record engine core** ✅ `core/{canon,rng,resolver,turn_record,atomic,
  engine_projection}.py` + `scripts/{engine_run,engine_recompute,validate_turn_replay}.py`. The
  contested-logistics slice runs end-to-end (validate_all → resolve → `reduce()` sole-constructor →
  O_EXCL durable commit → fog projection → record-replay + recomputation), all 12 PASS conditions green.
  **Delivers the once-deferred WP7.2 turn-replay** as a live `release` gate.
- **WP-E2a — first combat resolver** ✅ `core/salvo_resolver.py`: a DETERMINISTIC homogeneous Hughes
  salvo (Russia strike force vs Ukraine air defense, weekly, integer math, BDA + culmination),
  **UNCALIBRATED / ILLUSTRATIVE**. Generalized the turn record to be resolver-pluggable (a `resolver`
  param + a stored `ruleset` in the preimage) and the replay gate to a resolver registry.
- **ECI-2 / ECI-1 — engine-contract hygiene** ✅ `scripts/validate_engine_state.py` enforces the typed
  entity-type enum (additively extended with `STRIKE_FORCE`/`AIR_DEFENSE`), wired as a `release` gate;
  the agent-view projector allowlist is pinned so the salvo `ruleset` can't leak.
- **WP-E2 consolidation pass** ✅ closed the stale-committed-record class (the turn-replay gate now
  recomputes `transition_input_hash`; the contested record was regenerated), pinned the engine
  run-ledgers' inputs (`engine_state.yaml` + `rules.yaml`) + re-pinned `code_version` to a reachable SHA
  + made CI validate every example ledger, and reconciled this honest-status doc debt.
- **WP-E2b1 — heterogeneous salvo resolver** ✅ `core/salvo_resolver_het.py` (`ru_ua_salvo_heterogeneous`):
  DIAGONAL-FIRST over 3 threat classes (drone/cruise calibrated; ballistic an EXOGENOUS sourced range), an
  internal interceptor-magazine axis with a named allocation rule (`fixed-priority-best-first-v1`) + a
  saturation term, per-threat-subpool capped intercept (consumed decoupled), HYBRID culmination (sustained-k
  lethality streak OR inventory limb; magazine weeks-of-supply as a leading indicator), ruleset-range
  validation (a REJECTED transition — the crash-class fix), and a multi-turn-ready `TURN_ADVANCED`. New
  `scripts/validate_ruleset.py` (structure + provenance, a `release` gate) + `schemas/ruleset.schema.md`;
  the turn-replay gate is now fail-closed on an unknown `resolver_id` with per-resolver `STOCHASTIC_TERMINALS`.
  New `examples/ru_ua_salvo_heterogeneous/` golden record (the drone salvo exercises saturation). An
  adversarial-verify pass caught + fixed two bugs pre-commit. UNCALIBRATED / ILLUSTRATIVE.
- **WP-E2b2 — multi-turn campaign** ✅ `scripts/campaign_run.py` chains weekly turns over the het resolver
  (each turn's resulting_state — carrying the in-`reduce` `as_of_turn` advance via `TURN_ADVANCED` — is the
  next turn's start_state BYTE-IDENTICALLY); stops at culmination or the horizon. The committed
  `examples/ru_ua_salvo_multiturn/` campaign holds ~4 weeks, then magazines deplete and it CULMINATES at
  week 6 (sustained-k streak; the weeks-of-supply indicator leads the collapse). A cross-record
  **continuity gate** (a chain pass in `validate_turn_replay`: gap-free, digest-identical head handoffs,
  monotone `as_of_turn`, the successor pointer, one resolver/ruleset; a length-1 chain is a no-op so
  single-turn scenarios are unaffected) + a per-record **self-binding** check (`state_digest ==
  canonical_digest(state)`) — the latter from an adversarial-verify pass that caught a forged-state
  false-negative. `scripts/campaign_sensitivity.py` = culmination-as-RANGE over a resupply sweep (a derived
  report, not a gate): range [4,6] weeks, resupply-dominated. No `schema_version` bump.
- **WP-E2b3 — heterogeneous-salvo correctness fixes (external red-team NO-GO remediation)** ✅ An
  INDEPENDENT external red-team NO-GO'd the shipped het resolver; 5 findings verified as real shipped
  defects the E2b1/b2 verify MISSED, all fixed: **F3** monotone (was discontinuous/non-monotonic)
  saturation; **F4** round-ONCE-per-threat-subpool intercept (per-cell flooring dropped split-threat kills);
  **F5** ballistic band made non-decorative (brackets the central count, propagates an effective-rate band
  + a `verdict_indeterminate` flag) and the backwards ballistic leak range corrected to 60-80% leak
  (20-40% intercept; ballistics are HARD); **F6** culmination is now per-class **WEAKEST-LINK** (per-class
  floors drone 50 [LOCKED] / cruise 40 / ballistic 25, a ledgered contract extension) so a single-class
  collapse is no longer masked by pooling, the pooled inventory OR-limb is DROPPED (magazine = leading
  indicator per the locked contract), and the magazine indicator uses UNCONSTRAINED demand (+ a
  `stock_constrained` flag) so a starved week no longer reads "non-depleting"; **F7** stale `CALIBRATION
  TARGET` labels relabeled UNCALIBRATED (the E2c dossier found the channel not separably calibratable).
  Multiturn still culminates wk6 (now drone-driven, weakest-link); sensitivity sweep widened to
  {-100,-50,0,+100,+200}% → honest range wk5-8 (the +-50% band is flat once the inventory limb is gone).
  Records + ledgers + schema docs regenerated. Tighter property-specific adversarial-verify added
  (saturation monotonicity, multi-cell grain-invariance, magazine-under-starvation, per-class weakest-link).
- **WP-E2c — calibration-FEASIBILITY record + a Tier-1 hardening pass** ✅ The honest artifact the data
  dossier's verdict demanded: a new gate `scripts/validate_calibration_feasibility.py` (SEPARATE from the
  CALIBRATED gate, which is byte-unchanged) validates a committed `calibration_feasibility.yaml` that records
  the kinetic drone-intercept channel CANNOT be calibrated (mono-source, composite bucket, no method-independent
  corroborator), keeping `calibration_status: UNCALIBRATED` + a labeled descriptive band. Anti-over-claim teeth:
  verdict has no "feasible" value; a band is scanned (recursively, negation-aware) for affirmative
  calibrated/validated/corroborated language + must carry honesty labels; a provenance SHA exists only when
  PINNED (the piterfm v196 hash is honestly `null` + `BLOCKED_FETCH_AUTH_GATED`, never fabricated); a record
  under a CALIBRATED signoff is `contradictory-status`. `examples/ru_ua_salvo_heterogeneous/` carries the real
  record + `signoff.yaml`/`review.yaml` (attestation tier, UNCALIBRATED). The gate logic was adversarially-
  verified (a fresh skeptic found + we fixed a real escape — over-claims hidden in band lists/nested dicts) and
  the record content honesty-swept (every number traces to the dossier; verdict faithful; nothing fabricated).
  **Tier-1 hardening:** refreshed stale salvo run-ledger `code_version`s; corrected the stale rng_seeds/llm_steps
  "no engine yet" justification; an engine-state enum-audit test; and the 4 WP-E2b3 adversarial-verify
  properties locked in as **standing property sweeps** (each mutation-verified to have teeth).
- **WP-E2c.1 — honesty remediation of an external red-team (Gemini 5.5 Pro) pass** ✅ The verdict stays
  `NOT_FEASIBLE` and the model stays DETERMINISTIC / UNCALIBRATED / ILLUSTRATIVE; what changed is the
  packaging honesty around it (8 findings). **C1 (the keystone):** `attestation_kind: INDEPENDENT |
  SYNTHETIC_SELF_CHECK` now PARTITIONS the legal decision/verdict so a self-check structurally **cannot** spell
  APPROVED/ACCEPT; `release` reports the worst-kind banner `SELF-VERIFIED; NOT INDEPENDENTLY ATTESTED` (the bare
  word "attested" is gone) and iterates EVERY signoff-bearing scenario. Independence is **allow-listed** in
  `attestation_reviewers.yaml` (starts empty), not self-declared via a signer regex — a self-check cannot mint
  its own independence (`unlisted-independent-reviewer`). **C2:** the feasibility gate shifted from a word regex
  to STRUCTURE — unknown keys rejected at every object level, an `external_context` block pinned by
  machine-readable honesty enums (`comparison_role: CONTEXT_ONLY`, `calibration_effect: NONE`,
  `comparability_to_model_p`) with a clause-aware over-claim scan as defense-in-depth; the het record's observable
  corrected to the per-engagement-attempt `p` (not a launch-share) + the source crosswalk fixed (ISW removed,
  Defense Express vs ISIS separated, piterfm vs the ChrisO derivative named). **C3:** the disposition is now
  ENFORCED — the signoff DECLARES `calibration_disposition` and binds the record by id + sha256, so deleting it
  (`missing-feasibility-record`) or editing it without re-signing (`stale-feasibility-binding`) fails release; the
  dossier carries an honest `EXTERNAL_NOT_PINNED` hash status. **C4:** the affirmative "CALIBRATED axis" labels in
  the resolver / rules.yaml / the contract relabeled to "candidate / observable axis" (nothing is calibrated;
  comments seed future-loop premises). Built on a branch, green-gated, fresh-agent adversarially-verified; the
  merge is **human-gated** (a synthetic self-check must not self-merge an epistemically-sensitive path).
  WP-E2c.1 was reviewed + human-gated MERGED to origin/main, then **independently reviewed (cross-vendor AI;
  recorded reviewer: OpenAI GPT-5.5 Pro)** over 3 adversarial rounds. Round 1 caught a real HIGH fail-open four
  in-house adversarial-verify agents had MISSED — the feasibility release sweep globbed `examples/*/` while
  `verify.py`'s attestation coverage globs `examples/**/`, so a NESTED scenario could be attestation-covered yet
  feasibility-skipped (remediated: recursive `_sweep_dirs`; required fields in `launch_denominator_conflict.values`;
  stale review prose). Round 2 caught a coverage-superset precision gap (the sweep was not strictly a superset of
  the review-OR-signoff coverage set; remediated by adding the `review.yaml` term). Round 3 = **APPROVE**, and the
  **first genuine INDEPENDENT attestation was RECORDED** for the het scenario (reviewer added to
  `attestation_reviewers.yaml`; review/signoff → INDEPENDENT/ACCEPT/APPROVED; calibration stays
  UNCALIBRATED/NOT_FEASIBLE — the ACCEPT is of the WORK's soundness, not validity). The repo banner stays
  `SELF-VERIFIED; NOT INDEPENDENTLY ATTESTED` by worst-kind logic (ukraine is still a self-check).
- **Now:** the full suite passes (~805 tests); `release` exit 0 with the honest `SELF-VERIFIED; NOT INDEPENDENTLY
  ATTESTED` banner; the feasibility sweep reports `2 scenario(s) checked, 1 record(s) validated`. The lethality
  floors + k are LOCKED (drone 50 / cruise 40 / ballistic 25; k=3). Calibration *scoring* remains the sole
  `[SKIP]` (needs resolved outcomes).
- **WP-E2d (stochastic interception) — design-frozen, INDEPENDENTLY REVIEWED → NO-GO, SHELVED (2026-06-24).**
  A full frozen-contract spec (binomial-per-threat sampler, reuse `draw_index`, live PASS#6/#12, seed-
  conditioned culmination, a `SEED_CONDITIONED_SAMPLE` label, calibration-unchanged) was authored and put to a
  cross-vendor independent review (OpenAI GPT-5.5 Pro). **Verdict NO-GO:** no concrete decision survives the
  bar — the variance is assumption-propagation from an ASSUMED `p` (not empirical uncertainty), and a published
  seed-ensemble distribution would be professionally-packaged false precision, the exact thing the harness
  exists to prevent. (It also disproved the spec's claim of a magazine-drawdown distribution — depletion is
  fixed before interception, seed-invariant.) The model stays DETERMINISTIC / UNCALIBRATED; deterministic
  parameter-sensitivity is the right tool. Recorded in `centaur_engine_planning/ADJUDICATION_LEDGER.md` (the
  WP-E2d decision) + `WP-E2d_SPEC.md` (verdict header). A decoupled **engineering-only** RNG-assurance fixture
  (a synthetic test resolver, no analytical claim) is the one possible future path; an analytical revisit needs
  a named tail-probability decision + a defensible prior for `p` — not "more seeds."
- **WP-A1a (offline agent substrate) — BUILT.** The agent layer's first slice: two LLM players will eventually
  PLAY the wargame, but A1a builds only the OFFLINE, zero-network, deterministic command pipeline driven by
  **hand-authored response bytes** (no model is ever called). The one seam is the `commands` arg to
  `turn_record.assemble`. Shipped, each a green-gated + adversarially-verified slice: a strict parse-or-reject
  **extractor** (`core/command_extractor.py`); a turn-advancing **`agent_logistics`** resolver (delegates to the
  toy resolver + a `TURN_ADVANCED` event); the run-ledger **`llm_steps` migration** (non-causal provenance) +
  `schemas/llm_step.schema.md`; **`validate_agent_provenance.py`** — the H7 binding gate (re-extract from bytes,
  semantic-digest + harness-bound-identity + coverage), MANDATORY in `release`; the offline **drive**
  (`scripts/agent_offline_run.py`) + the first committed agent scenarios; **`validate_agent_fog.py`** — the
  differential no-leak gate (a viewer's view is a function of public state + outcome, never the secret threshold
  VALUE); the **tampered-binding** proof (a self-consistent tamper passes replay but fails provenance — the gate
  is non-redundant) + `@heldout` Goodhart probes; and a **multi-turn campaign** (chain check: byte-identical head
  handoff, monotone `as_of_turn`). Three committed agent scenarios (single-BLUE, two-player contested, 3-turn
  campaign) bind under every gate; `release` composes provenance + fog. **The OFFLINE substrate is a MACHINE log,
  never a forecast.** Explicitly UNBUILT (named in `verify.py`'s NOT_YET_IMPLEMENTED so the report never implies
  it passed): a LIVE model call (WP-A1b), and the transcript / judge / ENSEMBLE analysis layers (design-frozen
  and INDEPENDENTLY NO-GO'd — a decision-facing AI-playthrough transcript is false-validity). Disclosed residual:
  a fully self-consistent fabrication binds green (the gates prove consistency, not byte authenticity).
- **WP-A1b (offline machinery FOR a live call) — BUILT; the live CALL is deferred.** Externally adjudicated
  GO-WITH-CONTRACT (cross-vendor, 10 binding amendments) before the build. A1b lands the offline MACHINERY a
  future live model call needs, fully offline + green-gated, but makes **no call** (no network client, no spend,
  no Slice-0 probe — the substrate still only replays hand-authored bytes; no model is ever called). Shipped, each
  a green-gated slice with the highest-risk two adversarially verified: (1) a **closed-params extractor**
  (`EXTRACTOR_VERSION="2"` — closed per-action schema, no free-form/rationale field expressible); (2)
  **redact-at-source** (`core/response_redact.py` — an ALLOWLIST keeping only `tool_use` blocks before hashing)
  + a **global no-prose gate** (`validate_no_prose.py`, RELEASE-wired — every committed file, escape-proof) +
  the one-time prose re-baseline of the three example scenarios, closing the WP-A0 transcript disqualifier at
  the source; (3) the pure **prompt-template registry** (`core/prompt_templates.py`) with the **differential-
  purity invariant** + the **secret-sentinel scan** (proving the request's fixed parts are a pure function of
  `prompt_version`, secret-free); (4) the **Tier-3 request-envelope binding** in `validate_agent_provenance`
  (re-render a registered+approved template over the committed decision head's fog view, bind by sha256 —
  catching a self-consistent request tamper Tier-1 cannot; fail closed on unknown/unapproved versions); (5) the
  **network-import determinism gate** (`validate_no_network_imports.py`, RELEASE-wired — static AST scan, no
  network import in any green module) + a runtime `sys.modules` guard. The binding is **one leg of a three-
  legged AND** (binding ∘ fog no-leak ∘ template purity); alone it is not a no-leak proof — a leaky-but-
  registered template binds green, which the audited allowlist + the purity invariant catch. The
  ensemble/transcript/judge layers
  stay INDEPENDENTLY NO-GO'd (a `verify.py`-reporting guard test now pins that verbatim). Disclosed residual
  unchanged: a fully self-consistent fabricated capture binds green (consistency, not authenticity).
- **WP-A2a (illegal-move forfeit-recovery) — BUILT.** The first live capture exposed that a well-formed but
  engine-illegal AI move (BLUE `quantity 50` > 30; RED issuing `DISPATCH_SUPPLY`) made the resolver reject the
  WHOLE turn and the drive crash. Fixed by a third, VERIFIED disposition: `core/resolver.command_legality`
  (reuses `validate_all`); the drive (offline + the @live capture) pre-screens each command's legality on the
  harness-bound command and forfeits just the illegal mover to NO_OP, recorded as `ILLEGAL_FORFEIT` (digest +
  the resolver legality code). `validate_agent_provenance` re-verifies it: the bytes must re-extract, the
  recomputed legality must equal the recorded code, and the slot must have no command in the record
  (spurious-illegal-forfeit / illegal-forfeit-code-mismatch / illegal-forfeit-has-command). The resolver stays
  the strict authority (NOT weakened); model-RETRY was out of scope HERE (built later — see RED MATTERS +
  WP-A2 below). So a live game now survives an illegal move instead of crashing.

- **RED MATTERS — both roads blockable (a game-design refinement).** The WP-A3 games exposed a blind-spot: r2
  was a free un-blockable route, so BLUE always took it and RED was idle. Blockability is now PRESENCE-DERIVED:
  a road is blockable IFF a `route_secret:{route}` entity exists for it (`resolver.block_thresholds(state)`
  replaces the hardcoded `BLOCKABLE_WITH_THRESHOLD=("r1",)`; `resolve()` indexes the dispatched route's
  threshold). BACKWARD-COMPATIBLE by construction (old states lack `route_secret:r2` → identical behavior; all
  committed records replay byte-identically) and needs NO prompt change. A new `both_blockable_state()` builder
  + `agent_live_campaign --r2-threshold` add `route_secret:r2`; the committed LIVE game
  `examples/contested_logistics_both_blockable/` shows RED interdicting on a now-contested r2. The
  `ROUTE_SECRET` fog-filter hides the second secret automatically (sentinel + fog tests prove it).

- **WP-A2 — live model-RETRY.** When an AI order is rejected (extractor not-well-formed OR engine-illegal), the
  drive re-asks the model up to `--max-retries` (default 2) times, each retry appending a fixed CORRECTION
  clause naming ONLY the public reject code (`prompt_templates` `CORRECTION_CODES` = the extractor ∪ legality
  reject codes; no free-form coaching; the clause never names a hidden threshold). The shared loop
  `agent_offline_run.run_slot_attempts` is network-free (the live drive injects a network `fetch`), so offline
  + live cannot drift. Only the DECISIVE attempt (first legal COMMAND else the last) binds the 1:1 `llm_step`
  (with a `correction` field); the rejected PRIOR attempts are a non-binding, gate-VERIFIED `prior_attempts`
  list. `validate_agent_provenance._retry_problems` re-extracts each prior → it must GENUINELY reject (so a
  retry can't be fabricated and a legal move can't hide as a discarded prior), checks the correction chain, and
  re-hashes + (for a template version) re-renders each prior's bytes. The committed LIVE demo
  `examples/contested_logistics_retry/` shows retries firing (turn 3's chain: out-of-range → insufficient-supply
  → forfeit) — retry-EXHAUSTION, not recovery (an honest CAPTURE_ARTIFACT, n=1). The live scripts stay @live;
  the honesty work is offline-tested; a 3-lens adversarial-verify + a whole-increment review both ACCEPT.

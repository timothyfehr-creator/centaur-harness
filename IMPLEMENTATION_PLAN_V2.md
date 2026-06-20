# IMPLEMENTATION_PLAN_V2

**Status:** Canonical implementation plan  
**Version:** 2.0  
**Date:** 2026-06-18  
**Immediate next step:** WP1.2 — core schema skeletons. (WP0.1, WP0.2, and WP1.1 are complete; see [docs/PROGRESS.md](docs/PROGRESS.md) for live status.)

## 1. Goal

Turn the current centaur wargame scaffold into a disciplined, verifiable development harness before building deeper game mechanics.

The immediate objective is not a full wargame engine. It is to create minimum viable gates that prevent unsourced, unsafe, malformed, unreviewed, or non-reproducible outputs from appearing valid.

V2 preserves the useful core of the existing design: explicit scenarios, analytical probabilities, signposts, falsifiers, and mechanical verification. Build enforceable plumbing first; build richer simulation only after the gates work.

## 2. Non-goals

This plan does **not** attempt yet to build:

- a full autonomous AI-vs-AI wargame engine;
- institutional-grade governance;
- multi-run orchestration;
- cross-model replay;
- polished dashboards or reporting;
- a complete historical calibration suite;
- detailed military-domain models;
- a full OSINT ingestion platform;
- an extensive human SME workflow;
- a release-ready Ukraine/Russia scenario.

These are later. The repository first needs enforceable basics.

## 3. Sequencing principle

Build minimum viable enforcement first, then deeper game logic:

1. Establish repo-level verification and CI.
2. Make structured files machine-validatable.
3. Make factual baselines traceable to claims and sources.
4. Add basic safety and world-vs-game labeling.
5. Create a meaningful draft gate.
6. Add minimal agent grounding and information separation.
7. Add reproducibility and release gates only after draft mode works.
8. Defer modeling, replay, reporting, calibration, and multi-run work until the preceding gates exist.

Do not build the grand wargaming cathedral before the front door has a lock.

### Verification mode semantics

#### `scaffold` mode

Repo-level integrity only.

It should verify that the scaffold structure, existing checks, and basic required files are valid. It must **not** require:

- a fully sourced scenario;
- a complete factbase;
- agent grounding;
- fog-of-war enforcement;
- a run ledger;
- refuter review;
- human signoff;
- release artifacts.

The default invocation:

```bash
python scripts/verify.py
```

should remain equivalent to:

```bash
python scripts/verify.py --mode scaffold
```

until a deliberate change is approved.

#### `draft` mode

Draft mode must not imply analytical validity until source validation, agent grounding, and fog-of-war checks exist.

During early implementation, draft mode may be structural only. It must clearly report:

- checks currently active;
- checks not yet implemented;
- whether the result is merely structurally valid or analytically usable.

#### `release` mode

Release mode must never falsely pass.

Until release gates are implemented, it should either be unavailable or fail clearly with:

```text
release gate not implemented / not ready
```

### Anti-overbuild rule

Each work package must implement the smallest enforceable improvement that makes the repository safer or more verifiable.

Do not add broad governance, ingestion pipelines, dashboards, calibration frameworks, or full engine logic while implementing scaffold, schema, source, or safety primitives.

Do not begin the next work package automatically. Complete, verify, and review the current package first.

## 4. Phase plan

### Phase 0 — Repo baseline and CI

**Objective**  
Create a reliable baseline that Claude Code or Codex can run after every work package.

**Why now**  
Without CI and a basic scaffold check, every later change operates blind.

**P1 issues addressed**

- P1-1: verification gate too weak;
- P1-11: long-running coding security and data-loss controls too light.

**Deliverables**

- `python scripts/verify.py --mode scaffold`;
- default `python scripts/verify.py` preserved;
- minimal GitHub Actions workflow;
- basic secret scan;
- `.gitignore`;
- command-safety guidance.

**Likely files/directories**

```text
.github/workflows/ci.yml
.gitignore
docs/COMMAND_SAFETY.md
docs/PROGRESS.md
scripts/verify.py
scripts/secret_scan.py
tests/test_verify_modes.py
tests/test_secret_scan.py
tests/fixtures/secret_scan/
```

**Acceptance criteria**

- `python scripts/verify.py --mode scaffold` exits 0.
- `python scripts/verify.py` exits 0.
- Unknown modes exit nonzero with a clear error.
- `pytest` exits 0.
- CI runs scaffold verification and tests.
- Secret scan catches obvious fake secrets in fixtures.
- Existing checks remain green.

**Verification commands**

```bash
python scripts/verify.py --mode scaffold
python scripts/verify.py
python scripts/secret_scan.py
pytest
```

**Exit gate**  
The repo has a repeatable baseline check.

**Explicitly deferred**

- draft and release verification;
- source validation;
- safety enforcement beyond secret scanning;
- schema refactoring.

---

### Phase 1 — Enforceable schemas

**Objective**  
Replace informal schema-like documentation with machine-enforced validation for core structured files.

**Why now**  
Malformed YAML should fail before scenario, agent, evidence, or run logic depends on it.

**P1 issues addressed**

- P1-3: schemas are informal lists rather than enforceable contracts;
- P1-8: no schema-version or migration foundation.

**Deliverables**

- enforceable scenario schema;
- minimal enforceable schemas for agents, sources, claims, events, and turns;
- required `schema_version`;
- valid and invalid fixtures;
- schema validation integrated into scaffold verification.

**Likely files/directories**

```text
schemas/
scripts/validate_schemas.py
scripts/verify.py
examples/ukraine_crimea_logistics/*.yaml
tests/test_schema_validation.py
tests/fixtures/valid/
tests/fixtures/invalid/
```

**Acceptance criteria**

- valid fixtures pass;
- invalid fixtures fail for the expected reason;
- scenario files require:
  - `schema_version`;
  - branches and probabilities;
  - at least three signposts per branch;
  - at least one falsifier per branch;
  - probability rationale or update mechanism;
- current example files are changed only as needed to comply.

**Verification commands**

```bash
python scripts/validate_schemas.py
python scripts/verify.py --mode scaffold
python scripts/verify.py
pytest
```

**Exit gate**  
Core structured files can be rejected mechanically.

**Explicitly deferred**

- full migration framework;
- scenario plugin discovery;
- numeric state-scale system;
- semantic event or run logic.

---

### Phase 2 — Source, claim, and event validation

**Objective**  
Prevent real-world baselines from passing unless they resolve to source-backed claims or are explicitly labeled as assumptions.

**Why now**  
The scaffold contains real-world Ukraine/Russia scenario state. That cannot remain free-floating prose.

**P1 issues addressed**

- P1-2: source and evidence layer absent;
- partial P1-9: agents and scenario baselines not grounded.

**Deliverables**

```text
factbase/sources.yaml
factbase/claims.yaml
factbase/events.yaml
scripts/validate_sources.py
scripts/validate_claims.py
```

Minimal controlled vocabularies:

- source tier;
- claim confidence;
- state/output label.

**Likely files/directories**

```text
factbase/
schemas/source.schema.*
schemas/claim.schema.*
schemas/event.schema.*
scripts/validate_sources.py
scripts/validate_claims.py
scripts/verify.py
examples/ukraine_crimea_logistics/initial_state.yaml
examples/ukraine_crimea_logistics/scenario.yaml
tests/test_source_validation.py
tests/test_claim_validation.py
tests/fixtures/
```

**Acceptance criteria**

- every `REAL_WORLD_BASELINE` state item has claim references (WP2.3 decision: state
  sourcing triggers on the world-vs-game `label`; the original `CONFIRMED`/`LIKELY` clause
  was claim *confidence*, which is enforced on the claims themselves by `validate_claims`,
  not duplicated on state items);
- every claim resolves to source references;
- every source reference exists;
- Tier-3/social-only claims cannot be marked `CONFIRMED`;
- unsupported items are labeled `ASSUMPTION`, `MODEL_OUTPUT`, or `ILLUSTRATIVE`.

**Verification commands**

```bash
python scripts/validate_sources.py
python scripts/validate_claims.py
python scripts/verify.py --mode scaffold
python scripts/verify.py
pytest
```

**Exit gate**  
The example scenario cannot silently treat unsupported claims as facts.

**Explicitly deferred**

- automated OSINT ingestion;
- stale-claim confidence decay;
- source-conflict adjudication;
- database infrastructure.

---

### Phase 3 — Safety and output labeling

**Objective**  
Turn strategic-scope safety rules into executable minimum checks.

**Why now**  
The harness should support strategic assessment, not actionable operational guidance.

**P1 issues addressed**

- P1-6: safety constraints are prose-only.

**Deliverables**

```text
checks/safety_patterns.yaml
scripts/safety_check.py
```

Required labels:

```text
REAL_WORLD_BASELINE
ASSUMPTION
MODEL_OUTPUT
GAMED_FUTURE
ANALYST_JUDGMENT
ILLUSTRATIVE
```

**Likely files/directories**

```text
checks/safety_patterns.yaml
scripts/safety_check.py
docs/SAFETY_AND_SCOPE.md
scripts/verify.py
tests/test_safety_check.py
tests/fixtures/safety/
```

**Acceptance criteria**

- unsafe fixtures fail;
- safe strategic/logistics fixtures pass;
- unlabeled draft artifacts fail;
- draft verification invokes safety checks.

**Verification commands**

```bash
python scripts/safety_check.py tests/fixtures/safety/safe/
python scripts/safety_check.py tests/fixtures/safety/unsafe/  # expected failure
pytest
```

**Exit gate**  
Unsafe or unlabeled draft artifacts cannot pass.

**Explicitly deferred**

- semantic AI safety classifier;
- exhaustive policy engine;
- human legal-review workflow.

---

### Phase 4 — Draft verification mode

**Objective**  
Create the first meaningful gate distinguishing a valid scaffold from a structurally usable draft scenario.

**Why now**  
The repo needs an explicit status boundary before richer agent or game logic is added.

**P1 issues addressed**

- P1-1, P1-2, P1-3, P1-6.

**Deliverables**

```bash
python scripts/verify.py --mode scaffold
python scripts/verify.py --mode draft
```

Draft mode requires:

- schemas pass;
- sources, claims, and events resolve;
- safety checks pass;
- initial state is labeled;
- agents validate structurally.

Release mode should remain unavailable or fail clearly.

**Likely files/directories**

```text
scripts/verify.py
tests/test_verify_modes.py
examples/ukraine_crimea_logistics/
docs/PROGRESS.md
```

**Acceptance criteria**

- scaffold mode remains repo-level and lightweight;
- draft mode reports active and unimplemented checks;
- draft mode fails when schema, evidence, safety, or labeling checks fail;
- release mode cannot falsely pass;
- existing tests remain green.

**Verification commands**

```bash
python scripts/verify.py --mode scaffold
python scripts/verify.py
python scripts/verify.py --mode draft
python scripts/verify.py --mode release  # unavailable or expected clear failure
pytest
```

**Exit gate**  
The repo has an honest structural draft gate.

**Explicitly deferred**

- refuter review;
- human signoff;
- run replay;
- calibration;
- claims of analytical validity.

---

### Phase 5 — Minimum viable agent grounding

**Objective**  
Require agents to reference evidence, assumptions, or compact knowledge books rather than behaving as generic geopolitical chatbots.

**Why now**  
Agent quality is central to game quality, but grounding should remain minimal.

**P1 issues addressed**

- P1-9: agents too generic and ungrounded.

**Deliverables**

- small country/institution knowledge books;
- minimal assumption registry only where needed;
- validation of knowledge, evidence, and assumption references.

**Likely files/directories**

```text
knowledge/country_books/
knowledge/institution_books/
factbase/assumptions.yaml
schemas/agent.schema.*
scripts/validate_agents.py
scripts/verify.py
examples/ukraine_crimea_logistics/agents.yaml
tests/test_agent_validation.py
```

**Acceptance criteria**

- each agent has knowledge references;
- capability constraints resolve to claims or assumptions;
- behavioral assumptions resolve to assumption ids;
- ungrounded generic agents fail validation.

**Verification commands**

```bash
python scripts/validate_agents.py
python scripts/verify.py --mode draft
pytest
```

**Exit gate**  
Draft scenarios cannot use completely ungrounded agents.

**Explicitly deferred**

- encyclopedic country books;
- full doctrine libraries;
- SME-authored agent packs;
- automated retrieval orchestration.

---

### Phase 6 — Fog-of-war skeleton

**Objective**  
Enforce basic public/private state separation.

**Why now**  
Agents should not see the whole board by default.

**P1 issues addressed**

- P1-5: fog of war described but not enforced.

**Deliverables**

- public state file;
- private state files;
- context compiler;
- information-leak tests.

**Likely files/directories**

```text
core/context_compiler.py
state/public.yaml
state/private/
examples/ukraine_crimea_logistics/state/
schemas/state.schema.*
tests/test_context_compiler.py
scripts/verify.py
```

**Acceptance criteria**

- each agent receives only public state plus its permitted private state;
- unauthorized private fields do not appear in compiled contexts;
- adjudicator visibility is explicit;
- no full game engine is required.

**Verification commands**

```bash
pytest tests/test_context_compiler.py
python scripts/verify.py --mode draft
pytest
```

**Exit gate**  
Agent contexts can be generated without hidden-state leakage.

**Explicitly deferred**

- active deception;
- delayed intelligence;
- stale BDA mechanics;
- probabilistic sensing.

## 5. First implementation tranche

Complete only these work packages before expanding scope:

1. WP0.1 — Scaffold verification and CI
2. WP0.2 — Command safety and secret scan
3. WP1.1 — Enforceable scenario schema
4. WP1.2 — Core schema skeletons
5. WP2.1 — Source and claim registry validation

### WP0.1 — Scaffold verification and CI

**Objective**  
Create the baseline development gate.

**Scope**

- add `--mode scaffold` to `scripts/verify.py`;
- preserve current verification behavior;
- preserve default `python scripts/verify.py`;
- add tests for scaffold/default/invalid modes;
- add minimal GitHub Actions workflow.

**Out of scope**

- schemas;
- source validation;
- safety checks;
- draft mode;
- release mode;
- secret scanning;
- unrelated refactors.

**Likely files**

```text
scripts/verify.py
tests/test_verify.py or tests/test_verify_modes.py
.github/workflows/ci.yml
docs/PROGRESS.md  # only if already used
```

**Tests required**

- `--mode scaffold` works;
- default invocation works;
- unknown mode fails clearly;
- existing tests pass.

**Commands**

```bash
python scripts/verify.py --mode scaffold
python scripts/verify.py
pytest
```

**Done when**

- all commands pass;
- CI uses the same commands;
- existing checks are preserved;
- no later-phase work was added.

---

### WP0.2 — Command safety and secret scan

**Objective**  
Add basic protection for long-running coding sessions.

**Scope**

- add/update `.gitignore`;
- add `docs/COMMAND_SAFETY.md`;
- add `scripts/secret_scan.py`;
- add safe and unsafe fixtures;
- add secret scan to CI.

**Out of scope**

- full pre-commit framework;
- dependency-heavy security tooling;
- protected-file enforcement.

**Likely files**

```text
.gitignore
docs/COMMAND_SAFETY.md
scripts/secret_scan.py
tests/test_secret_scan.py
tests/fixtures/secret_scan/
.github/workflows/ci.yml
docs/PROGRESS.md
```

**Tests required**

- safe fixture passes;
- fake secret fixture fails;
- repo scan passes.

**Commands**

```bash
python scripts/secret_scan.py
python scripts/verify.py --mode scaffold
python scripts/verify.py
pytest
```

**Done when**

- CI includes secret scan;
- the unsafe fixture is caught;
- the repo passes;
- no broad security framework was added.

---

### WP1.1 — Enforceable scenario schema

**Objective**  
Make scenario validation schema-backed.

**Scope**

- choose JSON Schema or Pydantic after inspecting the repo;
- add scenario schema;
- require `schema_version`;
- preserve existing probability, signpost, falsifier, and rationale checks;
- add valid/invalid fixtures;
- wire scenario validation into scaffold verification.

**Out of scope**

- other schemas;
- source validation;
- draft mode;
- release mode.

**Likely files**

```text
schemas/scenario.schema.*
scripts/validate_schemas.py
scripts/verify.py
examples/ukraine_crimea_logistics/scenario.yaml
tests/test_schema_validation.py
tests/fixtures/valid/
tests/fixtures/invalid/
docs/PROGRESS.md
```

**Tests required**

Invalid fixtures for:

- missing `schema_version`;
- bad probability type;
- probability sum outside allowed range;
- missing falsifier;
- fewer than three signposts;
- missing rationale/update mechanism.

**Commands**

```bash
python scripts/validate_schemas.py
python scripts/verify.py --mode scaffold
python scripts/verify.py
pytest
```

**Done when**

- valid scenario passes;
- each invalid fixture fails for the expected reason;
- the current example scenario passes;
- existing checks remain green.

---

### WP1.2 — Core schema skeletons

**Objective**  
Add minimal enforceable schemas for agents, sources, claims, events, and turns.

**Scope**

- add schemas;
- require `schema_version`;
- add valid and invalid fixtures;
- extend schema validation tests.

**Out of scope**

- claim-to-source resolution;
- event semantics;
- agent grounding;
- run replay;
- draft or release mode.

**Likely files**

```text
schemas/agent.schema.*
schemas/source.schema.*
schemas/claim.schema.*
schemas/event.schema.*
schemas/turn.schema.*
scripts/validate_schemas.py
tests/test_schema_validation.py
tests/fixtures/valid/
tests/fixtures/invalid/
docs/PROGRESS.md
```

**Tests required**

- missing required fields fail;
- invalid enum values fail;
- wrong types fail;
- valid fixtures pass.

**Commands**

```bash
python scripts/validate_schemas.py
python scripts/verify.py --mode scaffold
python scripts/verify.py
pytest
```

**Done when**

- schemas exist and are enforceable;
- fixtures prove enforcement;
- scaffold verification remains green.

---

### WP2.1 — Source and claim registry validation

**Objective**  
Create the first evidence gate.

**Scope**

- add `factbase/sources.yaml`;
- add `factbase/claims.yaml`;
- validate claim-to-source resolution;
- add confidence and source-tier rules;
- add tests.

**Out of scope**

- event ledger validation;
- stale-claim decay;
- full OSINT ingestion;
- draft mode.

**Likely files**

```text
factbase/sources.yaml
factbase/claims.yaml
scripts/validate_sources.py
scripts/validate_claims.py
scripts/verify.py
tests/test_source_validation.py
tests/test_claim_validation.py
tests/fixtures/
docs/PROGRESS.md
```

**Tests required**

- valid claim resolves to a valid source;
- missing source reference fails;
- missing claim id fails;
- Tier-3/social-only claim marked `CONFIRMED` fails.

**Commands**

```bash
python scripts/validate_sources.py
python scripts/validate_claims.py
python scripts/verify.py --mode scaffold
python scripts/verify.py
pytest
```

**Done when**

- source and claim registries exist;
- resolver tests pass;
- scaffold verification remains green;
- no ingestion pipeline was added.

## 6. Later work

After the first tranche:

1. **WP2.2 — Event ledger validation**  
   Events reference claims; event confidence and category values validate.

2. **WP2.3 — Source or label the Ukraine example**  
   Real-world baselines require claim references or explicit assumption labels.

3. **WP3.1 — Safety checker**  
   Add minimum safety rules and safe/unsafe fixtures.

4. **WP3.2 — Output-label validation**  
   Require world-vs-game labels in draft artifacts.

5. **WP4.1 — Structural draft verification mode**  
   Compose schema, source, event, safety, and label checks.

6. **WP5.1 — Minimal agent grounding**  
   Add compact knowledge books and require references.

7. **WP6.1 — Public/private state partition**  
   Add state schemas.

8. **WP6.2 — Context compiler and leak tests**  
   Ensure unauthorized private state does not leak.

9. **WP7.1 — Minimal run-ledger schema**  
   Define run artifact format.

10. **WP7.2 — Replay/hash check**  
    Add a tamper-evident replay skeleton.

11. **WP8.1 — Review/signoff schemas**  
    Add lightweight refuter and human-signoff artifacts.

12. **WP8.2 — Release verification mode**  
    Release fails without sourcing, safety, replay, review, signoff, and calibration status.

13. **WP9.1 — Calibration/backtest marker**  
    Release outputs declare calibration status or carry `UNCALIBRATED ANALYTICAL JUDGMENT`.

## 7. Agent operating model

Recommended companion files:

```text
AGENTS.md
CLAUDE.md
docs/AGENT_WORKFLOW.md
```

Keep them short. They should enforce these rules:

1. Read this plan before changing code.
2. Implement only the named work package.
3. Explore first and write a short plan.
4. Preserve existing passing checks.
5. Add or update tests for every behavior change.
6. Run the exact acceptance commands.
7. Do not weaken verification to make tests pass.
8. Do not begin the next work package automatically.
9. Stop after two unsuccessful repair loops and report the blocker.
10. Report files changed, commands run, results, assumptions, and deferred work.

### Standard implementation loop

```text
EXPLORE
→ PLAN
→ IMPLEMENT ONE WORK PACKAGE
→ RUN TARGETED TESTS
→ RUN FULL ACCEPTANCE COMMANDS
→ SELF-REVIEW THE DIFF
→ REPORT
→ STOP
→ INDEPENDENT SCOPE REVIEW
→ FIX ONLY BLOCKERS
→ COMMIT
→ NEXT WORK PACKAGE
```

### Evaluation rule

Every work package should include, where applicable:

- one valid fixture;
- one invalid fixture;
- one regression test;
- exact acceptance commands.

Agent confidence is not an evaluation. Passing acceptance commands are the evaluation.

### Plan mode and goal mode

Use **plan mode** for repo inspection and work-package planning before edits.

Do **not** use persistent goal mode for WP0.1. Start using goal mode only after:

- scaffold verification is reliable;
- acceptance commands are deterministic;
- rollback/checkpoint behavior is understood.

Goal mode must remain scoped to one work package and must include explicit stop conditions.

### Hooks

Do not add elaborate hooks yet.

After WP0.1 and WP0.2, useful deterministic hooks may:

- run formatting;
- block obvious destructive commands;
- run targeted tests before completion.

Hooks must not:

- start the next work package;
- auto-commit before review;
- rewrite unrelated files;
- let an LLM grade its own architecture.

## 8. Backlog

Do not implement during the first tranche:

- tighter probability tolerance;
- scenario plugin discovery;
- numeric state scales and units;
- cross-model replay;
- full assumption registry;
- multi-run orchestration;
- rich dashboards;
- historical calibration suite;
- full domain-model library;
- extensive human SME workflow;
- full protected-file enforcement;
- pre-commit framework;
- stale-claim confidence decay;
- deception or delayed-intelligence modeling;
- detailed logistics/fuel/repair model.

## 9. Risks

### Schema rabbit hole

**Risk:** Weeks spent designing perfect schemas.  
**Mitigation:** Keep schemas minimal, fixture-driven, and tied to current work-package acceptance criteria.

### False confidence from simple safety patterns

**Risk:** Pattern matching misses subtle unsafe guidance.  
**Mitigation:** Treat the checker as a minimum gate, not a semantic oracle.

### Evidence layer becomes an OSINT platform

**Risk:** Source validation expands into ingestion and research infrastructure.  
**Mitigation:** Require only ids, tiers, confidence, and resolution at first.

### Agent grounding gets overbuilt

**Risk:** Country books become encyclopedias.  
**Mitigation:** Require only enough grounding to prevent generic roleplay.

### Release mode appears too early

**Risk:** Governance artifacts are built before draft mode works.  
**Mitigation:** Keep release unavailable or fail-closed until later.

### Dependency ambiguity

**Risk:** Schema design assumes unavailable packages.  
**Mitigation:** Choose JSON Schema or Pydantic during WP1.1 after repo inspection. Do not add dependencies casually.

### Repo drift

**Risk:** Paths differ from this plan.  
**Mitigation:** Every work-package prompt begins with repo exploration and a short plan.

## 10. Decision point

Stop planning and begin implementation when:

- this V2 scope is approved;
- the first tranche is limited to WP0.1, WP0.2, WP1.1, WP1.2, and WP2.1;
- the validation library will be chosen during WP1.1 after inspection;
- no release-mode or engine work begins before scaffold and draft gates exist.

Start with **WP0.1 only**.

After WP0.1:

1. run a narrow scope/diff review;
2. fix only blockers;
3. commit;
4. proceed to WP0.2 only after acceptance.

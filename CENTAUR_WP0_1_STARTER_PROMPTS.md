# CENTAUR HARNESS — STARTER PROMPTS

## Recommended use

Use the **Plan Mode prompt first**. It should inspect the live repository and validate that WP0.1 is executable without editing anything.

If the plan-mode output identifies no material blocker, exit plan mode and use the **WP0.1 implementation prompt**.

Do not use persistent goal mode for WP0.1.

---

## Prompt 1 — Plan Mode preflight

```text
You are preparing to implement WP0.1 from IMPLEMENTATION_PLAN_V2.md.

Operate in plan mode only. Do not edit files.

Explore the repository first. Read:
- IMPLEMENTATION_PLAN_V2.md
- README.md
- AGENTS.md, if present
- CLAUDE.md, if present
- docs/CONSTITUTION.md, if present
- scripts/verify.py
- existing tests
- any existing CI configuration
- project dependency/configuration files relevant to Python and testing

Evaluate WP0.1 only.

Report:

1. Current repository facts
   - actual paths relevant to WP0.1;
   - current scripts/verify.py behavior;
   - current default invocation behavior;
   - current test framework and command;
   - existing CI, if any;
   - Python version or dependency assumptions visible in the repo.

2. Minimal implementation plan
   - exact files expected to change;
   - exact behavior to add;
   - tests to add or update;
   - any compatibility concerns.

3. Acceptance-command check
   Confirm whether these commands are currently executable or what minimal adjustment is required:
   - python scripts/verify.py --mode scaffold
   - python scripts/verify.py
   - pytest

4. Blockers
   List only material blockers. Do not invent optional improvements.

Constraints:
- Do not propose draft mode.
- Do not propose release mode.
- Do not propose schemas.
- Do not propose source validation.
- Do not propose safety checks.
- Do not propose secret scanning.
- Do not propose unrelated refactors.
- Do not make scaffold mode depend on a fully sourced scenario.
- Do not add new dependencies unless strictly required.

End with exactly one recommendation:
- READY FOR WP0.1
- READY WITH THE FOLLOWING MINOR PATH/COMMAND ADJUSTMENTS
- BLOCKED FOR THE FOLLOWING MATERIAL REASON
```

---

## Prompt 2 — WP0.1 implementation

```text
Implement WP0.1 only: scaffold verification mode and minimal CI.

Explore the repo first. Read:
- IMPLEMENTATION_PLAN_V2.md
- README.md
- AGENTS.md, if present
- CLAUDE.md, if present
- docs/CONSTITUTION.md, if present
- scripts/verify.py
- existing tests
- any existing CI config

Before editing, write a concise implementation plan in your response or work log, then proceed unless you identify a material blocker.

The concise plan must state:
- files expected to change;
- current verify.py behavior;
- current test command;
- whether any referenced files are missing.

Scope:
- Add or update scripts/verify.py so it supports:
  python scripts/verify.py --mode scaffold
- Preserve the current verification behavior under scaffold mode.
- Preserve existing behavior for:
  python scripts/verify.py
- If no explicit mode behavior exists, make the default equivalent to --mode scaffold.
- Add tests proving:
  - --mode scaffold works;
  - default invocation still works;
  - invalid or unknown modes fail clearly.
- Add a minimal GitHub Actions workflow that runs:
  - python scripts/verify.py --mode scaffold
  - pytest
- If pytest is not configured or no tests exist, use the smallest test structure consistent with the repository. Do not add heavy dependencies.
- Do not implement draft mode.
- Do not implement release mode.
- Do not add source validation.
- Do not add safety checks.
- Do not add schemas.
- Do not add secret scanning.
- Do not refactor unrelated code.
- Do not make scaffold mode depend on the Ukraine example being fully sourced.
- Do not add new dependencies unless the repo already depends on them.

Likely files:
- scripts/verify.py
- tests/test_verify.py or tests/test_verify_modes.py
- .github/workflows/ci.yml
- docs/PROGRESS.md, only if the repo already uses it

Acceptance criteria:
- python scripts/verify.py --mode scaffold exits 0.
- python scripts/verify.py exits 0.
- pytest exits 0.
- Unknown mode exits nonzero with a clear error.
- CI workflow exists and uses the same intended commands.
- Existing checks are preserved.

Run verification:
- python scripts/verify.py --mode scaffold
- python scripts/verify.py
- pytest

Stop after WP0.1.

Report:
- files changed;
- tests added or updated;
- commands run;
- pass/fail results;
- assumptions made;
- anything deferred.
```

---

## Prompt 3 — Narrow post-implementation review

```text
Review the WP0.1 implementation against the approved scope.

Do not implement fixes yet.

Check only:
- Did it implement --mode scaffold?
- Did it preserve default python scripts/verify.py behavior?
- Did it avoid implementing draft, release, source, safety, schema, or secret-scan work prematurely?
- Did it add meaningful tests for scaffold, default, and invalid modes?
- Does CI run the intended minimal commands?
- Did it introduce new dependencies or unrelated refactors?
- Do the reported verification commands actually pass?
- Did it make scaffold mode depend on a fully sourced scenario?

Output:

1. Verdict:
   - ACCEPT
   - ACCEPT WITH MINOR FIXES
   - REJECT

2. Scope violations, if any

3. Missing acceptance criteria, if any

4. Test gaps, if any

5. Exact fix prompt, only if needed
```

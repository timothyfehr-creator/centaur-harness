#!/usr/bin/env python3
"""Centaur harness verification entry point.

Implements ``scaffold`` (repo-level integrity), ``draft`` (structural draft, WP4), and
``release`` (structural + attestation, WP8-9) modes.

- ``scaffold`` -- repo-level integrity + structural validation of any present
  scenario. Lightweight; does not require a sourced scenario.
- ``draft`` -- the first COMPOSED gate: it runs scaffold plus the source / claim /
  event / state / agent-grounding / safety gates and reports which checks are active
  versus not yet implemented. It is STRUCTURAL ONLY and never implies analytical validity
  (CONSTITUTION §3).
- ``release`` -- the release gate: draft's checks PLUS reproducibility (the run-ledger),
  the review + signoff attestations, and the calibration record (the evidence-or-label gate,
  WP9). It is STRUCTURAL + ATTESTATION ONLY -- a clean release means the package is complete,
  reproducible, attested, and carrying a (possibly evidence-backed) calibration status, NOT
  that the analysis is valid. It propagates the worst gate exit code (a gate that cannot run
  -> 2, findings -> 1), so it never falsely passes (§3).

A genuinely unknown mode (a typo) fails clearly (exit 2).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Repo root = parent of the scripts/ directory containing this file. Computed
# from __file__ so verification works regardless of the current directory.
REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_MODES = ("scaffold", "draft", "release")
DEFAULT_MODE = "scaffold"

# Files / directories that must exist for the scaffold to be considered intact.
# Keep this list minimal and repo-level only. Do NOT add scenario, factbase, or
# schema requirements here -- those belong to later work packages, and scaffold
# mode must not require a fully sourced scenario.
REQUIRED_PATHS = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/CONSTITUTION.md",
    "docs/COMMAND_SAFETY.md",
    "scripts/verify.py",
    "tests",
    ".github/workflows/ci.yml",
    ".gitignore",
)

# Gates composed into draft, in CI order -- each a standalone CLI in scripts/.
# validate_schemas.py is intentionally NOT here: verify_scaffold() already runs it
# in-process on examples/**/scenario.yaml, so re-subprocessing it would double-run the
# schema check; scaffold reuse supplies the plan's "schemas pass" requirement.
# secret_scan.py is also intentionally NOT here: it is a repo-integrity / hygiene check
# (WP0.2), not a structural draft check (CONSTITUTION §3) -- it runs as its own CI step.
# Draft is the structural-validity gate, not the secret boundary.
# verify.py must NEVER appear here -- draft would then subprocess itself (recursion).
DRAFT_GATES = (
    ("source registry", "validate_sources.py"),
    ("claim registry", "validate_claims.py"),
    ("event registry", "validate_events.py"),
    ("state (source-or-label)", "validate_state.py"),
    ("agent grounding", "validate_agents.py"),
    ("safety", "safety_check.py"),
)

# Gates release composes ON TOP of draft's checks (in CI order). The run-ledger
# (reproducibility / "replay") and the review+signoff attestation are release-ward axes,
# orthogonal to draft's structural-validity scope -- so they live here, not in DRAFT_GATES.
RELEASE_GATES = (
    ("run-ledger / reproducibility", "validate_run_ledger.py"),
    ("review + signoff attestation", "validate_review_signoff.py"),
    ("calibration record", "validate_calibration.py"),
)

# Checks the harness genuinely does NOT yet run. Draft AND release report these explicitly:
# neither may imply they passed (CONSTITUTION §3). Refuter review + human signoff (WP8) and the
# calibration RECORD (WP9, evidence-or-label) are now gated and run in `release`. What remains is
# COMPUTING calibration (a backtest), which -- like turn-replay -- needs the engine + outcomes.
NOT_YET_IMPLEMENTED = (
    "turn replay (engine run-record; no engine yet)",
    "calibration scoring (the harness records an external proper-scoring result; "
    "it does not compute one -- no engine)",
)

GATE_TIMEOUT_SECONDS = 120  # loose-by-design: ample headroom for a slow CI runner, not a tuned value


def verify_scaffold(repo_root: Path) -> list[str]:
    """Return a list of human-readable problems. An empty list means OK."""
    problems: list[str] = []
    for rel in REQUIRED_PATHS:
        if not (repo_root / rel).exists():
            problems.append(f"missing required path: {rel}")
    problems.extend(_scaffold_schema_problems(repo_root))
    return problems


def _scaffold_schema_problems(repo_root: Path) -> list[str]:
    """Structurally validate any scenario files that exist.

    Scaffold does NOT require a scenario, but it must FAIL CLOSED on one that is
    present yet cannot be validated (e.g. PyYAML missing) -- never silently pass.
    Sourcing is out of scope here (WP2.3); this is structural only.
    """
    scenarios = sorted(repo_root.glob("examples/**/scenario.yaml"))
    if not scenarios:
        return []  # scenarios are not required at scaffold time

    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    try:
        import validate_schemas  # imports PyYAML at module top
    except Exception as exc:  # PyYAML or module unavailable -> fail closed
        return [f"scenario schema: cannot validate scenarios ({exc})"]

    problems: list[str] = []
    for path in scenarios:
        rel = path.relative_to(repo_root).as_posix()
        for code, _where, msg in validate_schemas.validate_file(path):
            problems.append(f"scenario schema [{rel}]: {code}: {msg}")
    return problems


def _last_line(text: str) -> str:
    """Last non-empty, stripped line of `text` (a one-line check summary)."""
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _run_gate(repo_root: Path, script: str) -> dict:
    """Subprocess one gate CLI against its repo-default artifacts, captured.

    Returns {"name", "ok", "rc", "detail"}. Fail-closed: if the gate cannot launch
    (OSError) or hangs past the timeout, it is reported as a FAILED check (rc 2), never
    silently dropped -- a check that could not run must fail the draft, honestly.
    """
    cmd = [sys.executable, str(repo_root / "scripts" / script)]
    try:
        proc = subprocess.run(
            cmd, cwd=repo_root, capture_output=True, text=True,
            timeout=GATE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"name": script, "ok": False, "rc": 2,
                "detail": f"fail-closed: gate timed out after {GATE_TIMEOUT_SECONDS}s"}
    except OSError as exc:
        return {"name": script, "ok": False, "rc": 2,
                "detail": f"fail-closed: gate did not run ({exc})"}

    rc = proc.returncode
    if rc == 0:
        return {"name": script, "ok": True, "rc": 0,
                "detail": _last_line(proc.stdout) or "OK"}
    detail = _last_line(proc.stderr) or _last_line(proc.stdout) or f"exit {rc}"
    if rc == 2:
        detail = f"fail-closed: {detail}"
    return {"name": script, "ok": False, "rc": rc, "detail": detail}


def verify_draft(repo_root: Path) -> tuple[int, list[dict]]:
    """Self-contained structural draft gate. Returns (exit_code, check_results).

    exit_code is 0 only if EVERY active check passes; any check failing (a gate
    returning findings, fail-closed, or failing to run) fails the draft with exit 1.
    Draft adds no validation logic -- it composes the existing gates and reports.
    """
    results: list[dict] = []

    # Check 1: scaffold, reused IN-PROCESS (repo integrity + scenario schema). This
    # supplies "repo-level integrity" + "schemas pass" without a subprocess.
    scaffold_problems = verify_scaffold(repo_root)
    results.append({
        "name": "scaffold (repo integrity + scenario schema)",
        "ok": not scaffold_problems,
        "rc": 0 if not scaffold_problems else 1,
        "detail": "OK" if not scaffold_problems
        else f"{len(scaffold_problems)} problem(s); first: {scaffold_problems[0]}",
    })

    # Checks 2..N: the evidence + safety gates, each subprocessed (CI-faithful).
    for label, script in DRAFT_GATES:
        result = _run_gate(repo_root, script)
        result["name"] = f"{label} ({script})"
        results.append(result)

    exit_code = 0 if all(r["ok"] for r in results) else 1
    return exit_code, results


def _print_draft_report(results: list[dict], exit_code: int) -> None:
    """Print the honest draft report (CONSTITUTION §3): active checks, the checks that
    did NOT run, and a structural-only success line that disclaims analytical validity."""
    out = sys.stdout if exit_code == 0 else sys.stderr
    print("draft verification report (STRUCTURAL ONLY)", file=out)
    print("active checks:", file=out)
    for r in results:
        status = "PASS" if r["ok"] else "FAIL"
        print(f"  [{status}] {r['name']} -- {r['detail']}", file=out)

    print("the following checks did NOT run (not yet implemented; no analytical "
          "validity is implied):", file=out)
    for name in NOT_YET_IMPLEMENTED:
        print(f"  [SKIP] {name}", file=out)

    if exit_code == 0:
        print("draft verification OK -- STRUCTURAL ONLY, not an analytical-validity claim.",
              file=out)
    else:
        failed = [r["name"] for r in results if not r["ok"]]
        print(f"draft verification FAILED: {'; '.join(failed)}", file=out)


def _release_calibration(repo_root: Path) -> str:
    """The declared calibration_status of the example scenario's signoff for the release report
    line, enriched with the record's metric + N when CALIBRATED. Informational only -- the
    calibration gate (not this line) enforces; 'unknown' if unreadable."""
    signoffs = sorted(repo_root.glob("examples/**/signoff.yaml"))
    if not signoffs:
        return "unknown"
    try:
        import yaml
        doc = yaml.safe_load(signoffs[0].read_text(encoding="utf-8"))
        status = doc.get("calibration_status") if isinstance(doc, dict) else None
        if not (isinstance(status, str) and status.strip()):
            return "unknown"
        if status == "CALIBRATED":
            cal_path = signoffs[0].parent / "calibration.yaml"
            cal = yaml.safe_load(cal_path.read_text(encoding="utf-8")) if cal_path.is_file() else None
            if isinstance(cal, dict) and cal.get("metric") and cal.get("metric_value") is not None:
                return f"{status} ({cal['metric']} {cal['metric_value']}, N={cal.get('outcome_count')})"
        return status
    except Exception:
        return "unknown"


def verify_release(repo_root: Path) -> tuple[int, list[dict], str]:
    """The release gate: draft's checks + reproducibility + the review/signoff attestation +
    the calibration record. Returns (exit_code, check_results, calibration_status).

    Unlike draft, the exit code PROPAGATES THE WORST gate rc: 0 if all pass, 1 if any
    reports findings, 2 if any cannot run / times out (a fail-closed gate must not collapse
    to 1). Release adds no validation logic -- it composes the gates and reports (§3)."""
    _, results = verify_draft(repo_root)  # scaffold + DRAFT_GATES, reused

    for label, script in RELEASE_GATES:
        result = _run_gate(repo_root, script)
        result["name"] = f"{label} ({script})"
        results.append(result)

    worst = max(r["rc"] for r in results)
    return worst, results, _release_calibration(repo_root)


def _print_release_report(results: list[dict], exit_code: int, calibration: str) -> None:
    """The honest release report (CONSTITUTION §3): active checks, the still-not-built
    checks, and a success line that carries the declared calibration status and disclaims
    analytical validity. A clean release means complete + reproducible + attested, NOT valid."""
    out = sys.stdout if exit_code == 0 else sys.stderr
    print("release verification report (STRUCTURAL + ATTESTATION ONLY)", file=out)
    print("active checks:", file=out)
    for r in results:
        status = "PASS" if r["ok"] else "FAIL"
        print(f"  [{status}] {r['name']} -- {r['detail']}", file=out)

    print("the following checks did NOT run (not yet implemented; no analytical "
          "validity is implied):", file=out)
    for name in NOT_YET_IMPLEMENTED:
        print(f"  [SKIP] {name}", file=out)

    if exit_code == 0:
        print(f"release OK -- complete and attested; calibration: {calibration}; "
              "STRUCTURAL + ATTESTATION ONLY, not an analytical-validity claim.", file=out)
    else:
        failed = [r["name"] for r in results if not r["ok"]]
        print(f"release verification FAILED: {'; '.join(failed)}", file=out)


def run(mode: str, repo_root: Path) -> int:
    """Run the requested verification mode. Returns a process exit code."""
    if mode == "scaffold":
        problems = verify_scaffold(repo_root)
        if problems:
            print("scaffold verification FAILED:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print("scaffold verification OK")
        return 0

    if mode == "draft":
        exit_code, results = verify_draft(repo_root)
        _print_draft_report(results, exit_code)
        return exit_code

    if mode == "release":
        exit_code, results, calibration = verify_release(repo_root)
        _print_release_report(results, exit_code, calibration)
        return exit_code

    # Genuinely unknown mode (e.g. a typo). Every valid mode is now implemented.
    print(
        f"error: unknown mode {mode!r}. valid modes: {', '.join(VALID_MODES)}.",
        file=sys.stderr,
    )
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="Centaur harness verification (scaffold + draft modes).",
    )
    # No argparse `choices` here on purpose: we want a custom, descriptive error
    # for unknown modes (handled in run()), and we want main() to be unit-test
    # friendly by returning an exit code rather than raising SystemExit.
    parser.add_argument(
        "--mode",
        default=DEFAULT_MODE,
        help=(
            f"verification mode (default: {DEFAULT_MODE}). "
            f"valid: {', '.join(VALID_MODES)}"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args.mode, REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())

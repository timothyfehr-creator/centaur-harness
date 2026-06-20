"""Behavior tests for scripts/safety_check.py (the §7 minimum safety gate).

Mirrors the subprocess convention in test_secret_scan.py: invoke the real CLI so exit
codes match CI and the acceptance commands. The safe/unsafe fixtures are synthetic --
unsafe fixtures TRIGGER a pattern via the verb+object SHAPE while the instruction slot
is a placeholder (no real harmful content); that honesty property is itself asserted by
test_unsafe_fixtures_contain_no_concrete_procedure.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "scripts" / "safety_check.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "safety"
SAFE = FIXTURES / "safe"
UNSAFE = FIXTURES / "unsafe"
PATTERNS = REPO_ROOT / "checks" / "safety_patterns.yaml"


def _scan(*args: str, patterns: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if patterns is not None:
        env["CENTAUR_SAFETY_PATTERNS"] = str(patterns)
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _findings(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.lstrip().startswith("- ")]


def test_safe_fixture_passes() -> None:
    result = _scan(str(SAFE))
    assert result.returncode == 0, result.stderr


def test_unsafe_fixture_is_caught() -> None:
    # Default (conservative) tier catches the 5 conservative fixtures in the dir.
    result = _scan(str(UNSAFE))
    assert result.returncode == 1, result.stdout
    assert "cbrn_synthesis.yaml" in result.stderr


def test_bare_scan_passes_and_is_clean() -> None:
    # No args -> tracked files minus the safety fixtures/patterns. The whole repo
    # (incl. examples/ + factbase/) must be clean, and must actually scan files.
    result = _scan()
    assert result.returncode == 0, result.stderr
    assert "safety check OK" in result.stdout
    match = re.search(r"\((\d+) files\)", result.stdout)
    assert match and int(match.group(1)) > 0, result.stdout


# (fixture stem -> category token expected in the finding) for the CONSERVATIVE tier.
_CONSERVATIVE = {
    "cbrn_synthesis": "cbrn-synthesis",
    "explosive_construction": "explosive-construction",
    "stepwise_harm": "stepwise-harm-howto",
    "mass_casualty": "mass-casualty-howto",
    "precursor_procurement": "weaponization-procurement",
}


@pytest.mark.parametrize("stem,category", sorted(_CONSERVATIVE.items()))
def test_conservative_unsafe_fixture_single_fault(stem: str, category: str) -> None:
    result = _scan(str(UNSAFE / f"{stem}.yaml"))
    assert result.returncode == 1, result.stdout
    findings = _findings(result.stderr)
    assert len(findings) == 1, f"{stem}: expected exactly one finding; got {findings}"
    assert category in findings[0], f"{stem}: {findings[0]!r}"


@pytest.mark.parametrize("path", sorted(SAFE.glob("*.yaml")))
def test_safe_strategic_content_not_flagged(path: Path) -> None:
    # Each safe fixture individually must pass -- the strike-as-event and casualty-
    # outcome lines must not trip the gate (non-over-block).
    result = _scan(str(path))
    assert result.returncode == 0, f"{path.name} false-positived; stderr={result.stderr!r}"


# Procedure / method / quantity hints that an unsafe fixture must NOT contain -- a
# trigger line is a bare verb + object + <placeholder> with no actionable detail. These
# are deliberately NOT any rule's trigger verbs/objects, so a legitimate fixture never
# needs one. (Closes the "synthesize the anthrax using <X> in a lab" smuggling vector.)
_PROCEDURE_HINT = re.compile(
    r"(?i)\b(?:using|lab|laborator\w*|degrees?|celsius|fahrenheit|temperature|"
    r"incubat\w*|ferment\w*|distill\w*|extract\w*|centrifuge|reflux|recipe|"
    r"dosage|dose|gram|kilogram|millilit\w*|ratio|concentration)\b"
)


@pytest.mark.parametrize("path", sorted(UNSAFE.glob("*.yaml")))
def test_unsafe_fixtures_contain_no_concrete_procedure(path: Path) -> None:
    # Honesty invariant (machine-checked, not a reviewer promise): an unsafe fixture's
    # PAYLOAD (non-comment lines) is a bare verb+object trigger with an explicit
    # <placeholder> and NO real procedure -- no multi-digit quantity, no chemical-
    # formula-shaped token, and no procedure/method hint.
    text = path.read_text(encoding="utf-8")
    payload = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "<" in payload, f"{path.name}: no <placeholder> slot"
    assert re.search(r"\d{2,}", payload) is None, f"{path.name}: contains a quantity"
    assert re.search(r"\b[A-Z][a-z]?\d", payload) is None, f"{path.name}: formula-shaped token"
    assert _PROCEDURE_HINT.search(payload) is None, f"{path.name}: procedure/method hint"


def test_findings_are_redacted() -> None:
    # The full harmful-shaped line must never appear in output (so CI logs do not echo
    # it); only a masked span is shown, and the placeholder slot never leaks.
    result = _scan(str(UNSAFE))
    combined = result.stdout + result.stderr
    assert "<PLACEHOLDER>" not in combined
    assert "synthesize the <PLACEHOLDER> nerve agent" not in combined


def test_allowlist_marker_skips_line(tmp_path: Path) -> None:
    target = tmp_path / "doc.yaml"
    target.write_text(
        'a: "synthesize the <X> nerve agent"\n'
        'b: "synthesize the <X> nerve agent"  # pragma: allowlist safety\n'
    )
    result = _scan(str(target))
    # First line caught; the allowlisted line skipped -> exactly one finding.
    assert result.returncode == 1
    assert len(_findings(result.stderr)) == 1


def test_allowlist_marker_honored_in_default_scan(tmp_path: Path) -> None:
    # docs/SAFETY_AND_SCOPE.md carries a deliberately matching BLOCK example exempted by
    # the marker. Two-part proof of the DEFAULT (git ls-files) path: the same line with
    # the marker stripped IS caught, and the bare scan -- which includes that tracked
    # doc -- stays clean only because the marker is honored.
    doc = REPO_ROOT / "docs" / "SAFETY_AND_SCOPE.md"
    example = next(
        ln
        for ln in doc.read_text(encoding="utf-8").splitlines()
        if "pragma: allowlist safety" in ln and "nerve agent" in ln
    )
    stripped = tmp_path / "stripped.md"
    stripped.write_text(example.replace("<!-- pragma: allowlist safety -->", "") + "\n")
    assert _scan(str(stripped)).returncode == 1  # would match without the marker
    assert _scan().returncode == 0  # default scan includes the doc and honors the marker


def test_fail_closed_on_missing_patterns_file(tmp_path: Path) -> None:
    result = _scan(patterns=tmp_path / "nope.yaml")
    assert result.returncode == 2
    assert "Refusing to report a clean scan" in result.stderr


def test_fail_closed_on_empty_rules(tmp_path: Path) -> None:
    bad = tmp_path / "empty.yaml"
    bad.write_text('schema_version: "1.0"\nenabled_tiers: [conservative]\nrules: []\n')
    result = _scan(patterns=bad)
    assert result.returncode == 2


def test_fail_closed_on_unknown_tier(tmp_path: Path) -> None:
    # A typo'd tier must not silently filter to zero rules and pass everything.
    bad = tmp_path / "typo.yaml"
    bad.write_text(
        'schema_version: "1.0"\n'
        "enabled_tiers: [conservativ]\n"
        "rules:\n"
        "  - {id: r, tier: conservative, category: c, regex: 'x'}\n"
    )
    result = _scan(patterns=bad)
    assert result.returncode == 2


def test_fail_closed_on_duplicate_rule_id(tmp_path: Path) -> None:
    # A copy-paste error (two rules sharing an id) must fail closed, not silently load.
    bad = tmp_path / "dup.yaml"
    bad.write_text(
        'schema_version: "1.0"\n'
        "enabled_tiers: [conservative]\n"
        "rules:\n"
        "  - {id: dup, tier: conservative, category: c, regex: 'x'}\n"
        "  - {id: dup, tier: conservative, category: c, regex: 'y'}\n"
    )
    result = _scan(patterns=bad)
    assert result.returncode == 2


def _broadened_patterns(tmp_path: Path) -> Path:
    p = tmp_path / "broader.yaml"
    p.write_text(
        PATTERNS.read_text(encoding="utf-8").replace(
            "enabled_tiers: [conservative]", "enabled_tiers: [conservative, broader]"
        )
    )
    return p


# Each broader-tier fixture -> its category token. Both broader rules carry a fixture.
_BROADER = {
    "operational_targeting": "operational-targeting",
    "operational_strike_sequencing": "operational-sequencing",
}


@pytest.mark.parametrize("stem,category", sorted(_BROADER.items()))
def test_broader_tier_toggle(tmp_path: Path, stem: str, category: str) -> None:
    # Under the default conservative tier each broader fixture is clean; enabling the
    # broader tier catches it -- proving the tier parameterization toggles cleanly and
    # that both broader rules have explicit (single-fault) coverage.
    fixture = UNSAFE / f"{stem}.yaml"
    assert _scan(str(fixture)).returncode == 0  # conservative default: not flagged
    result = _scan(str(fixture), patterns=_broadened_patterns(tmp_path))
    assert result.returncode == 1
    findings = _findings(result.stderr)
    assert len(findings) == 1, f"{stem}: expected one finding; got {findings}"
    assert category in findings[0], f"{stem}: {findings[0]!r}"

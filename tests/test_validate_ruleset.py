"""Tests for scripts/validate_ruleset.py — the structural + provenance ruleset gate (WP-E2b1)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_ruleset as vr  # noqa: E402

SALVO_RULES = REPO_ROOT / "examples" / "ru_ua_salvo_homogeneous" / "rules.yaml"


def codes(findings: list) -> set:
    return {c for c, _w, _m in findings}


def doc(params: dict, **over) -> dict:
    d = {"schema_version": "1.0", "ruleset_id": "x", "ruleset_version": "1", "params": params}
    d.update(over)
    return d


# --- the shipped E2a ruleset + nesting --------------------------------------------

def test_committed_salvo_ruleset_validates() -> None:
    assert vr.validate_file(SALVO_RULES) == []


def test_flat_and_nested_provenance_trees_validate() -> None:
    params = {
        "p_intercept_pct": {
            "drone": {"value": 80, "source": "ASSUMED — calibration target"},
            "cruise": {"value": 65, "source": "ASSUMED"},
        },
        "threat_order": {"value": ["ballistic", "cruise", "drone"], "source": "ASSUMED — priority"},
        "k": {"value": 3, "source": "ASSUMED"},
        "on": {"value": True, "source": "ASSUMED"},
    }
    assert vr.validate_ruleset(doc(params), "x") == []


# --- provenance + canon-safety ----------------------------------------------------

def test_missing_source_is_flagged() -> None:
    assert "missing-source" in codes(vr.validate_ruleset(doc({"p": {"value": 80}}), "x"))


def test_float_value_is_flagged() -> None:
    out = vr.validate_ruleset(doc({"p": {"value": 0.8, "source": "ASSUMED"}}), "x")
    assert "float-not-allowed" in codes(out)


def test_float_inside_a_list_is_flagged() -> None:
    out = vr.validate_ruleset(doc({"p": {"value": [1, 2.0, 3], "source": "ASSUMED"}}), "x")
    assert "float-not-allowed" in codes(out)


def test_non_mapping_param_node_is_wrong_type() -> None:
    assert "wrong-type" in codes(vr.validate_ruleset(doc({"p": 5}), "x"))


# --- structural envelope ----------------------------------------------------------

def test_missing_schema_version() -> None:
    d = doc({"p": {"value": 1, "source": "ASSUMED"}})
    del d["schema_version"]
    assert "missing-schema-version" in codes(vr.validate_ruleset(d, "x"))


def test_missing_ruleset_id() -> None:
    d = doc({"p": {"value": 1, "source": "ASSUMED"}})
    del d["ruleset_id"]
    assert "missing-field" in codes(vr.validate_ruleset(d, "x"))


def test_empty_params_is_missing_field() -> None:
    assert "missing-field" in codes(vr.validate_ruleset(doc({}), "x"))


# --- CLI / discovery fail-closed --------------------------------------------------

def test_cli_default_finds_and_validates() -> None:
    assert vr.main([]) == 0


def test_cli_empty_dir_fails_closed(tmp_path: Path) -> None:
    assert vr.main([str(tmp_path)]) == 2


def test_cli_missing_path_is_usage_error(tmp_path: Path) -> None:
    assert vr.main([str(tmp_path / "nope.yaml")]) == 2

"""Tests for validate_engine_state.py -- the typed engine-state gate (ECI-2).

Covers the structural rules + the digest-scope rule, and proves the WP-E2a additive enum extension:
the salvo golden vector (STRIKE_FORCE / AIR_DEFENSE) validates, AND the original contested-logistics
types (FORCE / ROUTE / ROUTE_SECRET / SINK) still validate (backward compatibility).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

import canon  # noqa: E402
import validate_engine_state as ves  # noqa: E402

SALVO = REPO_ROOT / "examples" / "ru_ua_salvo_homogeneous" / "engine_state.yaml"


def codes(findings: list) -> set:
    return {c for c, _w, _m in findings}


def good_state(entities: list | None = None) -> dict:
    if entities is None:  # NB: an explicit [] must stay empty, so don't use `entities or [...]`
        entities = [{"id": "e1", "type": "FORCE", "fields": {"origin": {"value": 100, "unit": "units"}}}]
    return {"as_of_turn": 0, "entities": entities}


def envelope(state: dict | None = None, **extra) -> dict:
    doc = {"schema_version": "1.0", "state": state or good_state()}
    doc.update(extra)
    return doc


# --- the additive enum extension (ECI-2) ------------------------------------------

def test_salvo_golden_vector_validates_under_extended_enum() -> None:
    assert ves.validate_file(SALVO) == []          # STRIKE_FORCE / AIR_DEFENSE now legal


def test_original_contested_types_still_validate() -> None:
    ents = [{"id": t.lower(), "type": t, "fields": {"f": {"value": 1, "unit": "u"}}}
            for t in ("FORCE", "ROUTE", "ROUTE_SECRET", "SINK")]
    assert ves.validate_engine_state(envelope(good_state(ents)), "x") == []


def test_unknown_type_is_invalid_enum() -> None:
    bad = envelope(good_state(
        [{"id": "e", "type": "WARSHIP", "fields": {"f": {"value": 1, "unit": "u"}}}]))
    assert "invalid-enum" in codes(ves.validate_engine_state(bad, "x"))


# --- structural rules -------------------------------------------------------------

def test_missing_schema_version() -> None:
    doc = envelope()
    del doc["schema_version"]
    assert "missing-schema-version" in codes(ves.validate_engine_state(doc, "x"))


def test_state_must_be_a_mapping() -> None:
    bad = {"schema_version": "1.0", "state": []}
    assert "wrong-type" in codes(ves.validate_engine_state(bad, "x"))


def test_as_of_turn_bool_is_rejected() -> None:
    s = good_state()
    s["as_of_turn"] = True
    assert "wrong-type" in codes(ves.validate_engine_state(envelope(s), "x"))


def test_as_of_turn_negative_is_rejected() -> None:
    s = good_state()
    s["as_of_turn"] = -1
    assert "wrong-type" in codes(ves.validate_engine_state(envelope(s), "x"))


def test_empty_entities_is_missing_field() -> None:
    assert "missing-field" in codes(ves.validate_engine_state(envelope(good_state([])), "x"))


def test_duplicate_entity_id() -> None:
    e = {"id": "dup", "type": "FORCE", "fields": {"f": {"value": 1, "unit": "u"}}}
    findings = ves.validate_engine_state(envelope(good_state([e, dict(e)])), "x")
    assert "duplicate-id" in codes(findings)


def test_field_value_must_be_scalar() -> None:
    e = {"id": "e", "type": "FORCE", "fields": {"f": {"value": [1, 2], "unit": "u"}}}
    assert "wrong-type" in codes(ves.validate_engine_state(envelope(good_state([e])), "x"))


def test_field_unit_required() -> None:
    e = {"id": "e", "type": "FORCE", "fields": {"f": {"value": 1}}}
    assert "missing-field" in codes(ves.validate_engine_state(envelope(good_state([e])), "x"))


def test_bool_value_is_allowed() -> None:
    e = {"id": "e", "type": "AIR_DEFENSE", "fields": {"culminated": {"value": False, "unit": "bool"}}}
    assert ves.validate_engine_state(envelope(good_state([e])), "x") == []


# --- the digest-scope rule (optional at rest, enforced when present) ---------------

def test_state_digest_optional_when_absent() -> None:
    assert ves.validate_engine_state(envelope(), "x") == []          # bare input: no digest -> OK


def test_state_digest_matches_is_ok() -> None:
    s = good_state()
    assert ves.validate_engine_state(envelope(s, state_digest=canon.canonical_digest(s)), "x") == []


def test_state_digest_tampered_value_is_scope_violation() -> None:
    s = good_state()
    d = canon.canonical_digest(s)
    d["value"] = "0" * 64
    assert "digest-scope-violation" in codes(
        ves.validate_engine_state(envelope(s, state_digest=d), "x"))


def test_state_digest_over_whole_envelope_is_scope_violation() -> None:
    # the classic bug (WP-E1 C7): hashing {schema_version, state} instead of the `state` field only.
    s = good_state()
    wrong = canon.canonical_digest({"schema_version": "1.0", "state": s})
    assert "digest-scope-violation" in codes(
        ves.validate_engine_state(envelope(s, state_digest=wrong), "x"))


def test_state_digest_bad_shape_is_wrong_type() -> None:
    assert "wrong-type" in codes(ves.validate_engine_state(envelope(state_digest="nope"), "x"))


# --- CLI / discovery fail-closed --------------------------------------------------

def test_cli_default_finds_and_validates_salvo() -> None:
    assert ves.main([]) == 0


def test_cli_empty_dir_fails_closed(tmp_path: Path) -> None:
    assert ves.main([str(tmp_path)]) == 2           # no engine_state.yaml beneath -> refuse to pass


def test_cli_missing_path_is_usage_error(tmp_path: Path) -> None:
    assert ves.main([str(tmp_path / "nope.yaml")]) == 2


# --- enum-audit: the validator's enum and the schema doc must not drift (T3) ------

def test_entity_type_enum_matches_the_schema_doc() -> None:
    # The validator's ENTITY_TYPES is the live authority; the schema doc's Fields-table `type` row must
    # list exactly the same set. This locks the additive-extension discipline (ECI-2): a new entity type
    # added to the validator but not the doc (or vice-versa) is caught here, not discovered later.
    doc = (REPO_ROOT / "schemas" / "engine_state.schema.md").read_text(encoding="utf-8")
    type_row = next((ln for ln in doc.splitlines() if ln.lstrip().startswith("| `type`")), None)
    assert type_row is not None, "no `type` row found in engine_state.schema.md Fields table"
    documented = set(re.findall(r"`([A-Z][A-Z_]+)`", type_row))   # backtick-quoted ALL-CAPS enum tokens
    assert documented == set(ves.ENTITY_TYPES), (
        f"engine-state entity-type enum DRIFT: validator={sorted(ves.ENTITY_TYPES)} "
        f"vs schema doc={sorted(documented)}")

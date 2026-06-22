"""Tests for core/context_compiler.py (the WP6 fog-of-war context compiler).

In-process (the compiler is a library, not a CLI gate). The leak guarantee -- no agent
ever sees another agent's private state, and adjudicator-only state never reaches an agent
-- is proven by the negative tests; the fail-closed invariants by the FogError tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import context_compiler as cc  # noqa: E402
from validate_claims import load_registry  # noqa: E402
from validate_state import validate_state  # noqa: E402

FOG = REPO_ROOT / "tests" / "fixtures" / "fog"
VALID = FOG / "valid"
AGENT_IDS = {"agent-a", "agent-b"}
EXAMPLE = REPO_ROOT / "examples" / "ukraine_crimea_logistics"


def _ids(ctx: dict) -> set[str]:
    return {it["id"] for it in ctx["items"]}


@pytest.fixture
def partition() -> cc.Partition:
    return cc.load_partition(VALID, AGENT_IDS)


# --- positive: each agent sees public + its own private ---------------------------

def test_agent_sees_public_plus_own_private(partition: cc.Partition) -> None:
    assert _ids(cc.compile_context("agent-a", partition, AGENT_IDS)) == {"pub-1", "pub-2", "priv-a-1"}


def test_other_agent_sees_public_plus_its_own(partition: cc.Partition) -> None:
    assert _ids(cc.compile_context("agent-b", partition, AGENT_IDS)) == {"pub-1", "pub-2", "priv-b-1"}


def test_public_visible_to_every_agent(partition: cc.Partition) -> None:
    for aid in AGENT_IDS:
        assert {"pub-1", "pub-2"} <= _ids(cc.compile_context(aid, partition, AGENT_IDS))


def test_adjudicator_sees_all(partition: cc.Partition) -> None:
    assert _ids(cc.compile_context(cc.ADJUDICATOR_ID, partition, AGENT_IDS)) == {
        "pub-1", "pub-2", "priv-a-1", "priv-b-1", "adj-1"}


def test_compiled_context_is_valid_state_registry(partition: cc.Partition) -> None:
    # B3: in-process validate_state with an explicit empty claim set (the contexts use no
    # REAL_WORLD_BASELINE labels, so no claim refs) -> zero findings. No factbase coupling.
    for ctx in cc.compile_all(partition, AGENT_IDS).values():
        assert validate_state(ctx, "compiled", set()) == []


def test_deterministic_output(partition: cc.Partition) -> None:
    a = cc.compile_context("agent-a", partition, AGENT_IDS)
    b = cc.compile_context("agent-a", partition, AGENT_IDS)
    assert a == b and [i["id"] for i in a["items"]] == [i["id"] for i in b["items"]]


def test_inputs_not_mutated(partition: cc.Partition) -> None:
    import copy
    snapshot = copy.deepcopy(partition)
    cc.compile_all(partition, AGENT_IDS)
    assert partition == snapshot  # compiling does not mutate the partition


def test_compiled_context_carries_public_as_of_date(partition: cc.Partition) -> None:
    ctx = cc.compile_context("agent-a", partition, AGENT_IDS)
    assert ctx["as_of_date"] == "2026-06-22"  # public's; private files have none


# --- negative: no cross-agent or adjudicator-only leakage --------------------------

def test_agent_a_never_sees_agent_b_private(partition: cc.Partition) -> None:
    assert "priv-b-1" not in _ids(cc.compile_context("agent-a", partition, AGENT_IDS))
    assert "priv-a-1" not in _ids(cc.compile_context("agent-b", partition, AGENT_IDS))


@pytest.mark.parametrize("aid", sorted(AGENT_IDS))
def test_adjudicator_only_never_leaks_to_agents(partition: cc.Partition, aid: str) -> None:
    assert "adj-1" not in _ids(cc.compile_context(aid, partition, AGENT_IDS))


def test_universal_no_cross_leak(partition: cc.Partition) -> None:
    private_of = {"agent-a": "priv-a-1", "agent-b": "priv-b-1"}
    for aid in AGENT_IDS:
        others = {pid for other, pid in private_of.items() if other != aid}
        assert _ids(cc.compile_context(aid, partition, AGENT_IDS)).isdisjoint(others)


# --- fail-closed (FogError) --------------------------------------------------------

def test_unknown_agent_id_raises(partition: cc.Partition) -> None:
    with pytest.raises(cc.FogError):
        cc.compile_context("agent-ghost", partition, AGENT_IDS)


def test_agent_named_adjudicator_raises() -> None:
    # B2: an agent literally named "adjudicator" would see all private state -> refuse.
    with pytest.raises(cc.FogError):
        cc.load_partition(VALID, AGENT_IDS | {"adjudicator"})


# (fixture dir -> the invariant it violates). All must FogError at load time (B1: the
# orphan check is on the load path, independent of any compile entry point).
_INVALID = ["orphan", "collision", "empty_items", "missing_public", "version_mismatch"]


@pytest.mark.parametrize("case", _INVALID)
def test_invalid_partition_fails_closed_on_load(case: str) -> None:
    with pytest.raises(cc.FogError):
        cc.load_partition(FOG / "invalid" / case, AGENT_IDS)


# --- integration: the shipped example partition ------------------------------------

def test_example_partition_compiles_without_leak() -> None:
    # The shipped example partition, with agent ids discovered from its agents.yaml.
    agents_doc, _ = load_registry(EXAMPLE / "agents.yaml")
    aids = cc.known_agent_ids(agents_doc)
    contexts = cc.compile_all(cc.load_partition(EXAMPLE, aids), aids)
    public = {"pub-001", "pub-002"}
    assert _ids(contexts["agent-ua-logistics"]) == public | {"priv-ua-001"}
    assert _ids(contexts["agent-nato-jflc"]) == public | {"priv-nato-001"}
    assert _ids(contexts[cc.ADJUDICATOR_ID]) == public | {"priv-ua-001", "priv-nato-001", "adj-001"}
    # explicit leak checks: no agent sees the adjudicator-only item or the other's private
    assert "adj-001" not in _ids(contexts["agent-ua-logistics"])
    assert "adj-001" not in _ids(contexts["agent-nato-jflc"])
    assert "priv-nato-001" not in _ids(contexts["agent-ua-logistics"])
    assert "priv-ua-001" not in _ids(contexts["agent-nato-jflc"])

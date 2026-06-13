"""Catalog invariants — no network, no API keys.

These pin the contract that makes the catalog trustworthy: it covers exactly the
ACP registry snapshot, every classification is internally consistent, native
pointers resolve to real BenchFlow built-ins, and nothing shadows a built-in.
"""

import json
from pathlib import Path

import pytest
from benchflow.agents.registry import AGENTS

from acp_registry import ACP_AGENTS, BY_ID, NATIVE, WIRED, by_status
from acp_registry.catalog import (
    CATALOG,
    NPX,
    OUT_OF_SCOPE,
    VENDOR_LOCKED,
    _STATUSES,
)

_SNAPSHOT = json.loads(
    (Path(__file__).parents[1] / "registry.snapshot.json").read_text()
)
_SNAPSHOT_IDS = {a["id"] for a in _SNAPSHOT["agents"]}


def test_catalog_covers_exactly_the_registry_snapshot() -> None:
    """Every registry agent is classified, and the catalog invents none."""
    catalog_ids = set(BY_ID)
    missing = _SNAPSHOT_IDS - catalog_ids
    extra = catalog_ids - _SNAPSHOT_IDS
    assert not missing, f"registry agents not classified: {sorted(missing)}"
    assert not extra, f"catalog agents not in the registry snapshot: {sorted(extra)}"


def test_no_duplicate_ids() -> None:
    assert len(BY_ID) == len(ACP_AGENTS)


def test_status_partition_is_total() -> None:
    counts = {s: len(by_status(s)) for s in _STATUSES}
    assert sum(counts.values()) == len(ACP_AGENTS)
    # Sanity on the headline split (update if the registry snapshot is refreshed).
    assert counts[NATIVE] == 5
    assert counts[WIRED] >= 1


def test_native_pointers_resolve_to_builtins() -> None:
    for agent in by_status(NATIVE):
        assert agent.native_name in AGENTS, (
            f"{agent.registry_id} points at native {agent.native_name!r}, "
            "which is not a BenchFlow built-in"
        )


def test_wired_entries_are_routable_by_construction() -> None:
    for agent in by_status(WIRED):
        assert agent.distribution == NPX
        assert agent.bin_name
        assert agent.api_protocol
        assert agent.env_mapping, "wired agent must map a provider base URL/key"
        # Every env_mapping key must be a BENCHFLOW_PROVIDER_* var (the SDK
        # contract) and every target must be a non-empty agent-native var.
        for src, dst in agent.env_mapping.items():
            assert src.startswith("BENCHFLOW_PROVIDER_"), src
            assert dst
        # A wired agent must have *some* way to receive the model.
        assert agent.model_via in {"env", "config-option", "set_model"}
        if agent.model_via == "env":
            assert "BENCHFLOW_PROVIDER_MODEL" in agent.env_mapping


def test_wired_entries_have_no_launch_env() -> None:
    """register.py launches wired agents with a plain command (no env prefix)."""
    for agent in by_status(WIRED):
        assert not agent.launch_env, (
            f"{agent.registry_id}: wired agents can't carry launch_env yet "
            "(see register._launch_cmd)"
        )


def test_wired_and_catalog_do_not_shadow_builtins() -> None:
    """We must never register over a BenchFlow built-in name."""
    for agent in (*by_status(WIRED), *by_status(CATALOG)):
        assert agent.registry_id not in AGENTS, (
            f"{agent.registry_id} would shadow a built-in; "
            "mark it native or rename"
        )


def test_native_overlaps_are_marked_native_not_wired() -> None:
    """Registry ids that BenchFlow already ships are classified native."""
    builtin_overlap = {"claude-acp", "codex-acp", "gemini", "opencode", "pi-acp"}
    for rid in builtin_overlap:
        assert BY_ID[rid].status == NATIVE


@pytest.mark.parametrize("agent", ACP_AGENTS, ids=lambda a: a.registry_id)
def test_every_entry_has_a_rationale_and_source(agent) -> None:
    assert agent.summary
    # Non-native entries must justify their classification.
    if agent.status != NATIVE:
        assert agent.reason
    # BYO/locked claims must cite where they came from.
    if agent.status in {WIRED, CATALOG, VENDOR_LOCKED, OUT_OF_SCOPE}:
        assert agent.source.startswith("http")

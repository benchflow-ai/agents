"""Registration tests for wired agents — no network, no API keys, no sandbox.

Verifies each wired agent installs/launches with BenchFlow's proven JS-agent
plumbing and wires the gateway-routing contract the SDK relies on.
"""

import pytest
from benchflow.agents.registry import resolve_agent

from acp_registry import wired_agents
from acp_registry.register import _install_cmd, _launch_cmd, register


def test_register_returns_wired_ids() -> None:
    registered = register()
    assert set(registered) == {a.registry_id for a in wired_agents()}


def test_register_subset_rejects_non_wired() -> None:
    with pytest.raises(KeyError):
        register("stakpak")  # catalog, not wired


@pytest.mark.parametrize(
    "spec", wired_agents(), ids=lambda s: s.registry_id
)
def test_wired_agent_wires_gateway_routing_contract(spec) -> None:
    register(spec.registry_id)
    cfg = resolve_agent(spec.registry_id)
    assert cfg.protocol == "acp"
    assert cfg.api_protocol == spec.api_protocol
    assert cfg.env_mapping == spec.env_mapping
    assert cfg.acp_model_format == spec.acp_model_format
    assert cfg.supports_acp_set_model == spec.supports_acp_set_model
    assert cfg.requires_env == []


@pytest.mark.parametrize(
    "spec", wired_agents(), ids=lambda s: s.registry_id
)
def test_install_cmd_installs_and_verifies(spec) -> None:
    cmd = _install_cmd(spec)
    if spec.distribution == "npx":
        # Reuses BenchFlow's isolated Node bootstrap + npm-global install.
        assert "BF_NODE_VERSION" in cmd or "node" in cmd
        assert spec.package in cmd
    else:  # binary
        # Per-arch download from the vendored snapshot URL.
        assert "curl" in cmd and "uname -m" in cmd
        assert "https://" in cmd
    # Install ends with an existence check on the installed binary, not best-effort.
    assert spec.bin_name in cmd
    assert "[ -x" in cmd or "[ -d" in cmd or "[ -f" in cmd


@pytest.mark.parametrize(
    "spec", wired_agents(), ids=lambda s: s.registry_id
)
def test_launch_cmd_runs_acp_mode_with_constant_env(spec) -> None:
    cmd = _launch_cmd(spec)
    assert spec.bin_name in cmd
    if spec.acp_args:
        # acp_args may carry multiple flags; assert the first token is present.
        assert spec.acp_args.split()[0] in cmd
    for key, value in spec.launch_env.items():
        assert f"{key}={value}" in cmd


def test_qwen_code_specifics() -> None:
    """The flagship wired agent: pure-env OpenAI-compatible routing."""
    register("qwen-code")
    cfg = resolve_agent("qwen-code")
    assert cfg.api_protocol == "openai-completions"
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_BASE_URL"] == "OPENAI_BASE_URL"
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_API_KEY"] == "OPENAI_API_KEY"
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_MODEL"] == "OPENAI_MODEL"
    # No session/set_model: model is owned by env at launch.
    assert cfg.supports_acp_set_model is False

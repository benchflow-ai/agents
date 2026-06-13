"""Key-free registration + parity-invariant tests (no sandbox, no API keys).

Verifies the agent wires into BenchFlow with the gateway-routing + usage-capture
contract, and that the shipped server.mjs keeps the inside==outside parity fixes.
"""

from pathlib import Path

from ai_sdk_acp.register import _install_cmd, _launch_cmd, register
from benchflow.agents.registry import resolve_agent

_SERVER = (Path(__file__).parents[1] / "src" / "ai_sdk_acp" / "server.mjs").read_text()


def test_register_wires_gateway_routing_contract() -> None:
    register()
    cfg = resolve_agent("ai-sdk")
    assert cfg.protocol == "acp"
    assert cfg.api_protocol == "openai-completions"
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_BASE_URL"] == "OPENAI_BASE_URL"
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_API_KEY"] == "OPENAI_API_KEY"
    assert cfg.acp_model_format == "bare"
    assert cfg.supports_acp_set_model is True
    assert cfg.requires_env == []


def test_install_cmd_pins_deps_and_deploys_server() -> None:
    cmd = _install_cmd()
    assert "ai@6.0.204" in cmd
    assert "@ai-sdk/openai-compatible@2.0.50" in cmd
    assert "zod@4.4.3" in cmd
    assert "base64 -d" in cmd and "server.mjs" in cmd
    assert "node_modules/ai" in cmd  # install is verified, not best-effort


def test_launch_cmd_scrubs_latent_env_for_parity() -> None:
    cmd = _launch_cmd()
    for var in ("NODE_OPTIONS", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                "NODE_TLS_REJECT_UNAUTHORIZED"):
        assert f"-u {var}" in cmd
    assert "/bin/node" in cmd and "server.mjs" in cmd


def test_server_keeps_parity_invariants() -> None:
    # usage capture (agent self-reports finish.totalUsage via includeUsage)
    assert "includeUsage: true" in _SERVER
    # watchdog keepalive (feeds BenchFlow's idle watchdog during long tools)
    assert "withHeartbeat" in _SERVER
    # env scrub (proxy/TLS neutralized in-process)
    assert "NODE_TLS_REJECT_UNAUTHORIZED" in _SERVER
    # env-INDEPENDENT system prompt: the v1 "working in the directory <cwd>"
    # pattern that baked the absolute cwd into model-facing text must be GONE,
    # replaced by generic phrasing.
    assert "working in the directory" not in _SERVER
    assert "current working" in _SERVER
    assert "ToolLoopAgent" in _SERVER

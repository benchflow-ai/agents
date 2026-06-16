"""Key-free registration + invariant tests for the mimo-acp agent.

Runs with no sandbox and no API keys: it only inspects the AgentConfig that
``register()`` installs into BenchFlow's registry, plus the install/launch
command strings. Mirrors ai-sdk/harness-codex/tests/test_register.py and
mini-swe-acp/tests, adapted to MiMo's *native* ACP CLI (no server.mjs — mimo
IS the ACP server).
"""

from mimo_acp.register import _MIMO_BIN, _install_cmd, _launch_cmd, register
from benchflow.agents.registry import resolve_agent


def test_register_wires_mimo_native_acp() -> None:
    register()
    cfg = resolve_agent("mimo")
    assert cfg.name == "mimo"
    assert cfg.protocol == "acp"
    # Usage-capture for gateway-routed models lands in OPENAI_*; the free
    # mimo/mimo-auto channel needs no key.
    assert cfg.api_protocol == "openai-completions"
    # "bare" is required so the free mimo/mimo-auto id (no registered provider)
    # passes through set_model unchanged to MiMo's native catalog.
    assert cfg.acp_model_format == "bare"
    assert cfg.supports_acp_set_model is True


def test_install_pins_mimo_cli_no_server_mjs() -> None:
    cmd = _install_cmd()
    # Pinned npm package — reproducible (an unpinned float can break ACP).
    # Standardized at @0.1.1 across the agents-repo MiMo packages (the
    # live-validated current release; benchflow-core #679 pins @0.1.0).
    assert "@mimo-ai/cli@0.1.1" in cmd
    # Installs through BenchFlow's isolated node prefix, not the task image's.
    assert "/opt/benchflow" in cmd
    # mimo is a native ACP server: this package must NOT ship/deploy a server.mjs.
    assert "server.mjs" not in cmd


def test_launch_runs_mimo_acp() -> None:
    cmd = _launch_cmd()
    assert _MIMO_BIN in cmd
    assert cmd.strip().endswith("acp")  # `... mimo acp` — the native ACP server


def test_env_mapping_routes_openai_compatible() -> None:
    register()
    cfg = resolve_agent("mimo")
    # OpenAI-compatible gateway routing (repo convention; matches ai-sdk/acp):
    # the LiteLLM gateway URL + proxy key land in OPENAI_BASE_URL/OPENAI_API_KEY.
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_BASE_URL"] == "OPENAI_BASE_URL"
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_API_KEY"] == "OPENAI_API_KEY"


def test_alias_resolves_to_mimo() -> None:
    register()
    assert resolve_agent("mimo-code").name == "mimo"

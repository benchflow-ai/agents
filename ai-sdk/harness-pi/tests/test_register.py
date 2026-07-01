"""Key-free registration + server-invariant tests (no sandbox, no API keys)."""

from pathlib import Path

from ai_sdk_harness.register import _install_cmd, _launch_cmd, register
from benchflow.agents.registry import resolve_agent

_SERVER = (
    Path(__file__).parents[1] / "src" / "ai_sdk_harness" / "server.mjs"
).read_text()


def test_register_wires_harness_agent() -> None:
    register()
    cfg = resolve_agent("ai-sdk-pi")
    # the historical canonical name + the other alias keep resolving
    assert resolve_agent("ai-sdk-harness").name == "ai-sdk-pi"
    assert resolve_agent("pi-harness").name == "ai-sdk-pi"
    assert cfg.protocol == "acp"
    assert cfg.api_protocol == "openai-completions"
    # Pi's openrouter slot (chat-completions) is fed the provider base/key.
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_BASE_URL"] == "OPENROUTER_BASE_URL"
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_API_KEY"] == "OPENROUTER_API_KEY"
    assert cfg.acp_model_format == "bare"
    assert cfg.requires_env == []


def test_install_pins_canary_harness_and_deploys_server() -> None:
    cmd = _install_cmd()
    assert "@ai-sdk/harness@canary" in cmd
    assert "@ai-sdk/harness-pi@canary" in cmd
    assert "@ai-sdk/sandbox-just-bash@canary" in cmd
    assert "just-bash" in cmd
    assert "base64 -d" in cmd and "server.mjs" in cmd
    assert "node_modules/@ai-sdk/harness" in cmd  # verified, not best-effort


def test_launch_scrubs_env() -> None:
    cmd = _launch_cmd()
    for var in ("NODE_OPTIONS", "HTTP_PROXY", "NODE_TLS_REJECT_UNAUTHORIZED"):
        assert f"-u {var}" in cmd
    assert "/bin/node" in cmd and "server.mjs" in cmd


def test_server_keeps_integration_invariants() -> None:
    # HarnessAgent + Pi + local just-bash sandbox (real disk)
    assert "HarnessAgent" in _SERVER
    assert "@ai-sdk/harness-pi" in _SERVER
    assert "createJustBashSandbox" in _SERVER
    assert "ReadWriteFs" in _SERVER
    # FS bridge: session-dir <-> task cwd (sync-back + absolute-path symlink)
    assert "syncBackToCwd" in _SERVER
    assert "symlinkSync" in _SERVER
    # base normalization so Pi's openrouter slot posts {base}/v1/chat/completions
    assert "/v" in _SERVER

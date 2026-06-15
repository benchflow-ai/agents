"""Key-free registration + server-invariant tests (no sandbox, no API keys)."""

from pathlib import Path

from ai_sdk_harness_mimo.register import _install_cmd, register
from benchflow.agents.registry import resolve_agent

_SERVER = (
    Path(__file__).parents[1] / "src" / "ai_sdk_harness_mimo" / "server.mjs"
).read_text()


def test_register_wires_mimo_harness() -> None:
    register()
    cfg = resolve_agent("ai-sdk-mimo")
    assert cfg.name == "ai-sdk-mimo"
    assert cfg.protocol == "acp"
    assert cfg.api_protocol == "openai-completions"
    assert cfg.acp_model_format == "bare"
    assert cfg.supports_acp_set_model is True


def test_alias_resolves() -> None:
    register()
    assert resolve_agent("ai-sdk-harness-mimo").name == "ai-sdk-mimo"


def test_install_pins_harness_and_mimo_cli_no_vendor_harness() -> None:
    cmd = _install_cmd()
    assert "@ai-sdk/harness@canary" in cmd
    assert "@mimo-ai/cli@0.1.1" in cmd
    # MiMo is its own ACP agent — no vendor @ai-sdk/harness-<x> and no sandbox lib.
    assert "@ai-sdk/harness-pi" not in cmd
    assert "sandbox-just-bash" not in cmd
    # asserts the native mimo binary is present post-install
    assert "/node_modules/.bin/mimo" in cmd


def test_server_is_a_harnessagent_over_native_mimo_acp() -> None:
    assert "HarnessAgent" in _SERVER
    assert "createMimo" in _SERVER  # the thin custom HarnessV1 adapter
    assert '"acp"' in _SERVER or "'acp'" in _SERVER or "acp" in _SERVER
    assert "mimo" in _SERVER and "spawn(" in _SERVER  # spawns `mimo acp` on the host
    # NOT a vendor-library wrap: no vendor harness import, no sandbox-lib call.
    assert 'from "@ai-sdk/harness-pi"' not in _SERVER
    assert "createJustBashSandbox(" not in _SERVER
    assert 'from "@ai-sdk/harness/agent"' in _SERVER

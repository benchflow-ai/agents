"""Key-free registration + server-invariant tests (no sandbox, no API keys)."""

from pathlib import Path

from ai_sdk_harness_codex.register import _install_cmd, register
from benchflow.agents.registry import resolve_agent

_SERVER = (Path(__file__).parents[1] / "src" / "ai_sdk_harness_codex" / "server.mjs").read_text()


def test_register_wires_codex_harness() -> None:
    register()
    cfg = resolve_agent("ai-sdk-codex")
    assert cfg.protocol == "acp"
    assert cfg.api_protocol == "openai-responses"  # Codex = OpenAI Responses API
    assert cfg.acp_model_format == "bare"


def test_install_pins_canary_harness_and_vercel_sandbox() -> None:
    cmd = _install_cmd()
    assert "@ai-sdk/harness@canary" in cmd
    assert "@ai-sdk/harness-codex@canary" in cmd
    assert "@ai-sdk/sandbox-vercel@canary" in cmd  # bridge-backed → Vercel sandbox


def test_server_is_codex_on_vercel_sandbox() -> None:
    assert "createCodex" in _SERVER
    assert "createVercelSandbox" in _SERVER
    assert "HarnessAgent" in _SERVER
    # honestly flagged as not a benchflow-local eval
    assert "DOES NOT RUN" in _SERVER

"""Provider-routing policy for the mini-swe ACP shim.

mini-swe drives ``litellm.completion`` (chat-completions / anthropic-messages),
which can't speak the OpenAI Responses API. ``_litellm_prefix`` reconstructs the
litellm provider prefix from BenchFlow's resolved ``RUNTIME_PROVIDER_PROTOCOL``
so Azure (openai-completions) and Bedrock (openai-responses → anthropic-messages
surface for Claude models) route correctly.

The shim module is import-safe (no minisweagent import, no stdout redirect at
import time), so this runs without the sandbox runtime.
"""

import pytest

from mini_swe_acp.acp_shim import (
    _build_model,
    _is_anthropic_model,
    _litellm_prefix,
    _provider_env,
)

_PROVIDER_NAMES = ("MODEL", "PROTOCOL", "BASE_URL", "API_KEY")


@pytest.mark.parametrize(
    "protocol,model,expected",
    [
        ("openai-completions", "gpt-5.5", "openai"),
        ("openai-responses", "us.anthropic.claude-opus-4-7", "anthropic"),
        ("openai-responses", "openai.gpt-oss-20b-1:0", "openai"),
        ("anthropic-messages", "claude-sonnet-4-6", "anthropic"),
        ("openai-completions", "claude-via-openai-gateway", "openai"),
        ("", "gpt-4o-mini", ""),
    ],
)
def test_litellm_prefix(protocol: str, model: str, expected: str) -> None:
    assert _litellm_prefix(protocol, model) == expected


@pytest.mark.parametrize(
    "model,expected",
    [
        ("us.anthropic.claude-opus-4-7", True),
        ("claude-sonnet-4-6", True),
        ("gpt-5.5", False),
        ("openai.gpt-oss-20b-1:0", False),
        ("gemini-3.1-flash", False),
    ],
)
def test_is_anthropic_model(model: str, expected: bool) -> None:
    assert _is_anthropic_model(model) is expected


def _clear_provider_env(monkeypatch) -> None:
    for name in _PROVIDER_NAMES:
        for prefix in ("RUNTIME_PROVIDER_", "BENCHFLOW_PROVIDER_"):
            monkeypatch.delenv(prefix + name, raising=False)


def test_provider_env_reads_the_new_name_then_the_old(monkeypatch) -> None:
    """BenchFlow hands the agent RUNTIME_PROVIDER_*; older releases handed it
    BENCHFLOW_PROVIDER_*. The same shim reads both, the new name first."""
    _clear_provider_env(monkeypatch)
    assert _provider_env("MODEL") is None
    monkeypatch.setenv("BENCHFLOW_PROVIDER_MODEL", "old-name")
    assert _provider_env("MODEL") == "old-name"
    monkeypatch.setenv("RUNTIME_PROVIDER_MODEL", "new-name")
    assert _provider_env("MODEL") == "new-name"


@pytest.mark.parametrize("prefix", ["RUNTIME_PROVIDER_", "BENCHFLOW_PROVIDER_"])
def test_model_is_wired_to_the_endpoint_under_either_name(monkeypatch, prefix) -> None:
    pytest.importorskip("minisweagent")
    _clear_provider_env(monkeypatch)
    for name, value in (
        ("MODEL", "runtime-vllm-fake-policy"),
        ("PROTOCOL", "openai-completions"),
        ("BASE_URL", "http://127.0.0.1:4000/v1"),
        ("API_KEY", "sk-test"),
    ):
        monkeypatch.setenv(prefix + name, value)

    model = _build_model({}, "")

    assert model.config.model_name == "openai/runtime-vllm-fake-policy"
    assert model.config.model_kwargs == {
        "api_base": "http://127.0.0.1:4000/v1",
        "api_key": "sk-test",
    }

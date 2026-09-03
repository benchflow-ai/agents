"""Agents-owned unit coverage for canonical OpenClaw ACP shim."""

from __future__ import annotations

import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    ("model", "cap"),
    [
        ("gpt-5.4", 128000),
        ("openai/gpt-5.4", 128000),
        ("us-openai/gpt-5.4", 128000),
        ("azure-foundry-openai/gpt-5.4", 128000),
        ("benchflow-openai-gpt-5.4", 128000),
        ("claude-sonnet-4-6", 128000),
        ("claude-opus-4-6", 128000),
        ("claude-opus-4-7", 128000),
        ("claude-opus-4-8", 128000),
        ("claude-sonnet-5", 128000),
        ("claude-opus-5-1", 128000),
        ("anthropic/claude-opus-5", 128000),
        ("anthropic/claude-sonnet-5-2", 128000),
        ("azure-foundry-anthropic/claude-sonnet-4-6", 128000),
        ("benchflow-anthropic-claude-opus-5", 128000),
        ("claude-sonnet-4-60", None),
        ("claude-sonnet-5-beta", None),
        ("claude-opus-5-1-2", None),
        ("claude-opus-50", None),
        ("not-claude-sonnet-5", None),
        ("evil/claude-opus-5", None),
        ("evil/gpt-5.4", None),
    ],
)
def test_model_token_caps(shim, model: str, cap: int | None) -> None:
    """Guards BenchFlow PR #1074 model output-cap compatibility."""
    assert shim._default_max_tokens(model) == cap


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, "128000"),
        ("invalid", "128000"),
        ("-1", "128000"),
        ("127999", "127999"),
        ("128000", "128000"),
        ("128001", "128000"),
        ("9" * 5000, "128000"),
    ],
)
def test_max_token_config_is_capped(
    shim, configured: str | None, expected: str
) -> None:
    """Guards BenchFlow PR #1074 against invalid OpenClaw maxTokens."""
    assert shim._max_tokens_value("claude-sonnet-5", configured) == expected


def test_uncapped_model_preserves_configured_max_tokens(shim) -> None:
    """Guards BenchFlow PR #1075 uncapped-model pass-through."""
    assert shim._max_tokens_value("other-model", "invalid") == "invalid"


def test_workspace_links_task_and_copies_first_skill_source(
    shim, tmp_path, monkeypatch
) -> None:
    """Guards BenchFlow PR #1075 workspace/skill behavior."""
    home = tmp_path / "home"
    work = tmp_path / "task"
    skill = home / ".claude" / "skills" / "demo"
    skill.mkdir(parents=True)
    work.mkdir()
    (skill / "SKILL.md").write_text("# demo\n")
    monkeypatch.setenv("HOME", str(home))

    shim.setup_workspace(str(work))

    assert (home / ".openclaw" / "workspace").resolve() == work
    assert (work / "skills" / "demo" / "SKILL.md").read_text() == "# demo\n"


def test_openai_auth_preserves_existing_profiles(shim, tmp_path, monkeypatch) -> None:
    """Guards BenchFlow PR #1075 native OpenAI auth-store merge."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    path = tmp_path / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"anthropic": {"apiKey": "ant-test"}}))

    shim.setup_openai_auth()

    assert json.loads(path.read_text()) == {
        "anthropic": {"apiKey": "ant-test"},
        "openai": {"apiKey": "sk-test"},
    }


def test_openai_auth_without_key_is_noop(shim, tmp_path, monkeypatch) -> None:
    """Guards BenchFlow PR #1075 no-key auth behavior."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    shim.setup_openai_auth()
    path = tmp_path / ".openclaw" / "agents" / "main" / "agent" / "auth-profiles.json"
    assert not path.exists()


def test_gcloud_adc_writes_credentials_and_enables_plugin(
    shim, tmp_path, monkeypatch
) -> None:
    """Guards BenchFlow PR #1075 Vertex ADC/plugin setup seam."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(
        "GOOGLE_APPLICATION_CREDENTIALS_JSON", '{"type":"authorized_user"}'
    )
    calls = []
    monkeypatch.setattr(
        shim.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    shim.setup_gcloud_adc()

    adc = tmp_path / ".config" / "gcloud" / "application_default_credentials.json"
    assert adc.read_text() == '{"type":"authorized_user"}'
    assert shim.os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == str(adc)
    assert calls[0][0][0] == [shim._OPENCLAW_BIN, "plugins", "enable", "google"]


def test_custom_provider_merges_config_and_model_metadata(
    shim, tmp_path, monkeypatch
) -> None:
    """Guards BenchFlow PR #1075 custom-provider config format."""
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / ".openclaw" / "openclaw.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"other": True, "models": {"providers": {"old": {}}}}))
    models = [{"id": "m", "name": "Model"}]

    shim.setup_custom_provider(
        "custom",
        "https://api.test/v1",
        "secret",
        "openai-responses",
        models,
    )

    config = json.loads(path.read_text())
    assert config["other"] is True
    assert config["models"]["providers"]["old"] == {}
    assert config["models"]["providers"]["custom"] == {
        "baseUrl": "https://api.test/v1",
        "api": "openai-responses",
        "apiKey": "secret",
        "models": models,
    }


def test_generic_provider_env_configures_stripped_model(
    shim, tmp_path, monkeypatch
) -> None:
    """Guards BenchFlow PR #670 generic env fallback without BenchFlow imports."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("BENCHFLOW_PROVIDER_BASE_URL", "https://proxy.test/v1")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_API_KEY", "key")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_PROTOCOL", "openai-completions")
    monkeypatch.setenv(
        "BENCHFLOW_PROVIDER_MODELS",
        '[{"id":"deepseek-v4-flash","name":"DeepSeek"}]',
    )

    assert shim._find_and_setup_provider("deepseek-v4-flash") == "custom"
    config = json.loads((tmp_path / ".openclaw" / "openclaw.json").read_text())
    models = config["models"]["providers"]["custom"]["models"]
    assert models[0]["id"] == "deepseek-v4-flash"


def _provider_config(name: str = "deepseek") -> SimpleNamespace:
    return SimpleNamespace(
        base_url=f"https://{name}.test/v1",
        url_env=f"{name.upper()}_BASE_URL",
        auth_type="api_key",
        auth_env=f"{name.upper()}_API_KEY",
        api_protocol="openai-completions",
        models=[{"id": f"{name}-model", "name": name.title()}],
    )


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("deepseek-v4-flash", "deepseek"),
        ("glm-4.6", "glm"),
        ("qwen3.6-max-preview", "qwen-dashscope"),
        ("minimax-m2.7", "minimax"),
        ("gemini-3.1-flash-lite", "google"),
        ("gpt-4o", "openai"),
        ("o1-preview", "openai"),
        ("o3-mini", "openai"),
        ("whatever-7b", "anthropic"),
        ("claude-sonnet-4-6", "anthropic"),
    ],
)
def test_provider_prefix_uses_registry_then_native_heuristics(
    shim, fake_providers, model: str, expected: str
) -> None:
    """Guards BenchFlow PR #670 provider inference order."""
    registry = {
        "deepseek-v4-flash": "deepseek",
        "glm-4.6": "glm",
        "qwen3.6-max-preview": "qwen-dashscope",
        "minimax-m2.7": "minimax",
    }
    fake_providers.find_provider_for_bare_model = lambda value: (
        (registry[value], _provider_config(registry[value]))
        if value in registry
        else None
    )
    assert shim._infer_provider_prefix(model) == expected


@pytest.mark.parametrize("provider", ["deepseek", "glm"])
def test_bare_custom_provider_uses_registry_config(
    shim, fake_providers, monkeypatch, provider: str
) -> None:
    """Guards BenchFlow PR #670 provider-specific endpoint registration."""
    model = f"{provider}-model"
    cfg = _provider_config(provider)
    fake_providers.find_provider_for_bare_model = lambda value: (
        (provider, cfg) if value == model else None
    )
    monkeypatch.setenv(cfg.url_env, cfg.base_url)
    monkeypatch.setenv(cfg.auth_env, f"{provider}-key")
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))

    assert shim._setup_bare_custom_provider(model) == provider
    assert calls == [
        (
            provider,
            cfg.base_url,
            f"{provider}-key",
            cfg.api_protocol,
            cfg.models,
        )
    ]


@pytest.mark.parametrize(
    "model",
    [
        "gemini-3.1-flash-lite",
        "gpt-4o",
        "o3-mini",
        "claude-sonnet-4-6",
        "whatever-7b",
    ],
)
def test_native_and_unknown_bare_models_do_not_register(
    shim, fake_providers, monkeypatch, model: str
) -> None:
    """Guards BenchFlow PR #670 native/unknown no-setup behavior."""
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))
    assert shim._setup_bare_custom_provider(model) is None
    assert calls == []


def test_bare_registry_match_without_env_does_not_register(
    shim, fake_providers, monkeypatch
) -> None:
    """Guards BenchFlow PR #670 missing-provider-config behavior."""
    cfg = _provider_config()
    fake_providers.find_provider_for_bare_model = lambda _model: ("deepseek", cfg)
    monkeypatch.delenv(cfg.url_env, raising=False)
    monkeypatch.delenv(cfg.auth_env, raising=False)
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))
    assert shim._setup_bare_custom_provider("deepseek-v4-flash") is None
    assert calls == []


def test_generic_env_wins_when_registry_config_unresolvable(
    shim, fake_providers, monkeypatch
) -> None:
    """Guards BenchFlow PR #670 generic fallback before inferred prefix."""
    cfg = _provider_config()
    fake_providers.find_provider_for_bare_model = lambda _model: ("deepseek", cfg)
    monkeypatch.setenv("BENCHFLOW_PROVIDER_BASE_URL", "https://proxy.test/v1")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_API_KEY", "generic-key")
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))

    assert shim._resolve_bare_model_prefix("deepseek-v4-flash") == "custom"
    assert calls[0][:3] == ("custom", "https://proxy.test/v1", "generic-key")


def test_registry_config_wins_over_generic_env(
    shim, fake_providers, monkeypatch
) -> None:
    """Guards BenchFlow PR #670 provider-specific precedence."""
    cfg = _provider_config()
    fake_providers.find_provider_for_bare_model = lambda _model: ("deepseek", cfg)
    monkeypatch.setenv(cfg.url_env, cfg.base_url)
    monkeypatch.setenv(cfg.auth_env, "specific-key")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_BASE_URL", "https://proxy.test/v1")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_API_KEY", "generic-key")
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))

    assert shim._resolve_bare_model_prefix("deepseek-v4-flash") == "deepseek"
    assert calls[0][:3] == ("deepseek", cfg.base_url, "specific-key")


def test_no_provider_config_keeps_inferred_prefix(
    shim, fake_providers, monkeypatch
) -> None:
    """Guards BenchFlow PR #670 no-config provider inference."""
    cfg = _provider_config()
    fake_providers.find_provider_for_bare_model = lambda _model: ("deepseek", cfg)
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))
    assert shim._resolve_bare_model_prefix("deepseek-v4-flash") == "deepseek"
    assert calls == []


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gemini-3.1-flash-lite", "google"),
        ("gpt-4o", "openai"),
        ("o3-mini", "openai"),
        ("claude-sonnet-4-6", "anthropic"),
        ("whatever-7b", "anthropic"),
    ],
)
def test_native_and_unknown_prefixes_need_no_registration(
    shim, fake_providers, monkeypatch, model: str, expected: str
) -> None:
    """Guards BenchFlow PR #670 native/unknown resolution behavior."""
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))
    assert shim._resolve_bare_model_prefix(model) == expected
    assert calls == []


@pytest.mark.parametrize(
    ("models_json", "expected_models"),
    [
        ('[{"id":"m","name":"Model"}]', [{"id": "m", "name": "Model"}]),
        ("not-json", []),
    ],
)
def test_generic_env_preserves_protocol_and_handles_model_metadata(
    shim, fake_providers, monkeypatch, models_json: str, expected_models: list[dict]
) -> None:
    """Guards BenchFlow PR #670 generic provider env contract."""
    monkeypatch.setenv("BENCHFLOW_PROVIDER_BASE_URL", "https://proxy.test/v1")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_API_KEY", "key")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_PROTOCOL", "anthropic-messages")
    monkeypatch.setenv("BENCHFLOW_PROVIDER_MODELS", models_json)
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))

    assert shim._find_and_setup_provider("model") == "custom"
    assert calls == [
        (
            "custom",
            "https://proxy.test/v1",
            "key",
            "anthropic-messages",
            expected_models,
        )
    ]


def test_generic_env_without_base_url_does_not_register(
    shim, fake_providers, monkeypatch
) -> None:
    """Guards BenchFlow PR #670 incomplete generic provider config."""
    monkeypatch.setenv("BENCHFLOW_PROVIDER_API_KEY", "key")
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))
    assert shim._find_and_setup_provider("model") is None
    assert calls == []


def test_generic_env_uses_adc_when_api_key_is_absent(
    shim, fake_providers, monkeypatch
) -> None:
    """Guards BenchFlow PR #670 generic Vertex ADC fallback."""
    monkeypatch.setenv("BENCHFLOW_PROVIDER_BASE_URL", "https://vertex.test/v1")
    monkeypatch.setattr(shim, "_get_adc_token", lambda: "adc-token")
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))

    assert shim._find_and_setup_provider("model") == "custom"
    assert calls[0][:3] == ("custom", "https://vertex.test/v1", "adc-token")


@pytest.mark.parametrize(
    ("auth_type", "auth_env", "expected_key"),
    [
        ("api_key", "PROVIDER_API_KEY", "provider-key"),
        ("none", None, ""),
        ("adc", None, "adc-token"),
    ],
)
def test_registry_provider_auth_modes(
    shim,
    fake_providers,
    monkeypatch,
    auth_type: str,
    auth_env: str | None,
    expected_key: str,
) -> None:
    """Guards BenchFlow PR #670 registry provider auth modes."""
    cfg = SimpleNamespace(
        base_url="https://provider.test/v1",
        url_env=None,
        auth_type=auth_type,
        auth_env=auth_env,
        api_protocol="openai-completions",
        models=[],
    )
    if auth_env:
        monkeypatch.setenv(auth_env, expected_key)
    monkeypatch.setattr(shim, "_get_adc_token", lambda: "adc-token")
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))

    assert shim._setup_provider_from_config("provider", cfg) == "provider"
    assert calls[0][:3] == ("provider", cfg.base_url, expected_key)


def test_registry_provider_missing_api_key_does_not_register(
    shim, fake_providers, monkeypatch
) -> None:
    """Guards BenchFlow PR #670 missing registry API key behavior."""
    cfg = SimpleNamespace(
        base_url="https://provider.test/v1",
        url_env=None,
        auth_type="api_key",
        auth_env="PROVIDER_API_KEY",
        api_protocol="openai-completions",
        models=[],
    )
    calls = []
    monkeypatch.setattr(shim, "setup_custom_provider", lambda *args: calls.append(args))
    assert shim._setup_provider_from_config("provider", cfg) is None
    assert calls == []


@pytest.mark.parametrize(
    ("provider", "requested", "configured"),
    [
        ("google-vertex", "gemini-3-flash", "google-vertex/gemini-3-flash"),
        ("anthropic-vertex", "claude-sonnet-4-6", "anthropic-vertex/claude-sonnet-4-6"),
        ("", "gemini-3-flash", "google/gemini-3-flash"),
        ("", "gpt-4o", "openai/gpt-4o"),
        ("", "claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
    ],
)
def test_set_model_preserves_provider_model_formats(
    shim, monkeypatch, provider: str, requested: str, configured: str
) -> None:
    """Guards BenchFlow PR #1075 model-prefix reconstruction behavior."""
    monkeypatch.setattr(shim, "setup_openai_auth", lambda: None)
    monkeypatch.setattr(shim, "setup_gcloud_adc", lambda: None)
    if provider:
        monkeypatch.setenv("BENCHFLOW_PROVIDER_NAME", provider)
    else:
        monkeypatch.delenv("BENCHFLOW_PROVIDER_NAME", raising=False)
    calls = []
    monkeypatch.setattr(
        shim.subprocess,
        "run",
        lambda args, **kwargs: calls.append(args),
    )
    inbox = iter(
        [{"id": 1, "method": "session/set_model", "params": {"modelId": requested}}]
    )
    monkeypatch.setattr(shim, "recv", lambda: next(inbox))
    monkeypatch.setattr(shim, "send", lambda _: None)

    with pytest.raises(StopIteration):
        shim.main()

    assert calls[0][-2:] == ["agents.defaults.model", configured]


def test_set_model_writes_generation_params_and_surfaces_failure(
    shim, monkeypatch, capsys
) -> None:
    """Guards BenchFlow PR #871 diagnostic ACK and PR #1074 param ordering."""
    monkeypatch.setattr(shim, "setup_openai_auth", lambda: None)
    monkeypatch.setattr(shim, "setup_gcloud_adc", lambda: None)
    monkeypatch.setenv("BENCHFLOW_MODEL_MAX_TOKENS", "128001")
    monkeypatch.setenv("BENCHFLOW_MODEL_TEMPERATURE", "0.5")
    monkeypatch.setenv("BENCHFLOW_MODEL_TOP_P", "0.9")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[-2] == "agents.defaults.params.topP":
            raise RuntimeError("topP failed")

    monkeypatch.setattr(shim.subprocess, "run", run)
    inbox = iter(
        [
            {
                "id": 7,
                "method": "session/set_model",
                "params": {"modelId": "anthropic/claude-sonnet-5"},
            }
        ]
    )
    monkeypatch.setattr(shim, "recv", lambda: next(inbox))
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)

    with pytest.raises(StopIteration):
        shim.main()

    assert [call[-2:] for call in calls] == [
        ["agents.defaults.model", "anthropic/claude-sonnet-5"],
        ["agents.defaults.params.maxTokens", "128000"],
        ["agents.defaults.params.temperature", "0.5"],
        ["agents.defaults.params.topP", "0.9"],
    ]
    acks = [m for m in sent if m.get("id") == 7 and "result" in m]
    assert acks == [{"jsonrpc": "2.0", "id": 7, "result": {}}]
    assert not any(m.get("id") == 7 and "error" in m for m in sent)
    thought = next(
        m
        for m in sent
        if m.get("params", {}).get("update", {}).get("sessionUpdate") == "agent_thought"
    )
    assert "topP failed" in thought["params"]["update"]["text"]
    assert "topP failed" in capsys.readouterr().err


def test_parse_session_jsonl_emits_text_thought_tool_and_result(shim, tmp_path) -> None:
    """Guards BenchFlow PR #1075 JSONL-to-ACP trajectory mapping."""
    path = tmp_path / "session.jsonl"
    rows = [
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "plan"},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "shell",
                        "input": {"command": "pwd"},
                    },
                    {"type": "text", "text": "done"},
                ],
            },
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolCallId": "t1",
                "content": [{"type": "text", "text": "out"}],
            },
        },
    ]
    path.write_text("not-json\n" + "\n".join(json.dumps(row) for row in rows))

    updates = shim.parse_session_jsonl(path, "session-1")

    assert [u["params"]["update"]["sessionUpdate"] for u in updates] == [
        "agent_thought",
        "tool_call",
        "text_update",
        "tool_call_update",
    ]
    assert all(u["params"]["sessionId"] == "session-1" for u in updates)


def test_parse_missing_session_is_safe_fallback(shim, tmp_path) -> None:
    """Guards BenchFlow PR #1075 missing-trajectory fallback."""
    assert shim.parse_session_jsonl(tmp_path / "missing.jsonl", "s") == []


def test_send_serializes_worker_and_dispatch_output(shim, monkeypatch) -> None:
    class Sink:
        def __init__(self):
            self.guard = threading.Lock()
            self.active = 0
            self.max_active = 0
            self.lines = []

        def write(self, line):
            with self.guard:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.005)
            self.lines.append(line)
            with self.guard:
                self.active -= 1

        def flush(self):
            pass

    sink = Sink()
    monkeypatch.setattr(shim.sys, "stdout", sink)
    barrier = threading.Barrier(8)

    def emit(index):
        barrier.wait()
        shim.send({"index": index})

    threads = [threading.Thread(target=emit, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sink.max_active == 1
    assert sorted(json.loads(line)["index"] for line in sink.lines) == list(range(8))


def _row(text: str) -> str:
    return json.dumps(
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            },
        }
    )


def _prompt_thread(shim, monkeypatch, tmp_path, code: str, **kwargs):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    state = shim._PromptState()
    token = object()
    assert state.reserve(token)
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    worker = threading.Thread(
        target=shim._run_prompt,
        args=(
            state,
            token,
            3,
            "acp-session",
            (sys.executable, "-c", code, str(sessions)),
            dict(os.environ),
            sessions,
        ),
        kwargs={"poll_interval": 0.01, **kwargs},
    )
    state.set_worker(token, worker)
    worker.start()
    return state, worker, sent, sessions


def _wait_until(predicate, timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.01)


def test_prompt_streams_update_before_child_exit(shim, monkeypatch, tmp_path) -> None:
    release = tmp_path / "release"
    code = f"""
import json, pathlib, sys, time
d = pathlib.Path(sys.argv[1]); p = d / 'live.jsonl'
p.write_text({(_row("live") + chr(10))!r})
while not pathlib.Path({str(release)!r}).exists(): time.sleep(.01)
print(json.dumps({{'meta': {{'agentMeta': {{'sessionId': 'live'}}}}}}))
"""
    state, worker, sent, _ = _prompt_thread(shim, monkeypatch, tmp_path, code)
    _wait_until(lambda: any(m.get("method") == "session/update" for m in sent))
    with state.lock:
        assert state.process.poll() is None
    release.touch()
    worker.join(3)
    assert not worker.is_alive()
    update_index = next(
        i for i, m in enumerate(sent) if m.get("method") == "session/update"
    )
    response_index = next(i for i, m in enumerate(sent) if m.get("id") == 3)
    assert update_index < response_index


def test_session_tailer_deduplicates_and_sticks(shim, tmp_path) -> None:
    old = tmp_path / "old.jsonl"
    old.write_text(_row("old") + "\n")
    tailer = shim._SessionTailer(tmp_path)
    old.write_text(old.read_text() + _row("new") + "\n")
    assert [u["params"]["update"]["text"] for u in tailer.poll("s")] == ["new"]
    assert tailer.poll("s") == []
    unrelated = tmp_path / "unrelated.jsonl"
    unrelated.write_text(_row("unrelated") + "\n")
    assert tailer.poll("s") == []
    old.write_text(old.read_text() + _row("later") + "\n")
    assert [u["params"]["update"]["text"] for u in tailer.drain("s", None)[0]] == [
        "later"
    ]


def test_session_tailer_ambiguity_truncation_and_stdout_recovery(
    shim, tmp_path
) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text(_row("old-1") + "\n")
    second.write_text(_row("old-2") + "\n")
    ambiguous = shim._SessionTailer(tmp_path)
    first.write_text(first.read_text() + _row("new-1") + "\n")
    second.write_text(second.read_text() + _row("new-2") + "\n")
    assert ambiguous.poll("s") == []
    updates, diagnostic = ambiguous.drain("s", "second")
    assert [u["params"]["update"]["text"] for u in updates] == ["new-2"]
    assert diagnostic is None

    sticky = shim._SessionTailer(tmp_path)
    first.write_text(first.read_text() + _row("sticky") + "\n")
    assert sticky.poll("s")
    updates, diagnostic = sticky.drain("s", "second")
    assert updates == []
    assert "mismatch" in diagnostic
    first.write_text(_row("replacement") + "\n")
    assert [u["params"]["update"]["text"] for u in sticky.poll("s")] == ["replacement"]
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text(_row("new-inode") + "\n")
    replacement.replace(first)
    assert [u["params"]["update"]["text"] for u in sticky.poll("s")] == ["new-inode"]


def test_session_tailer_detects_same_size_rewrite(shim, tmp_path) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text(_row("first") + "\n")
    tailer = shim._SessionTailer(tmp_path)
    path.write_text(_row("added") + "\n")
    baseline_mtime_ns = tailer.baseline[path][3]
    os.utime(path, ns=(baseline_mtime_ns + 1, baseline_mtime_ns + 1))
    assert tailer.poll("s")
    mtime_ns = path.stat().st_mtime_ns
    path.write_text(_row("other") + "\n")
    os.utime(path, ns=(mtime_ns + 1, mtime_ns + 1))
    updates = tailer.poll("s")
    assert [u["params"]["update"]["text"] for u in updates] == ["other"]


def test_prompt_cancel_is_responsive_and_reaps(shim, monkeypatch, tmp_path) -> None:
    code = f"""
import pathlib, sys, time
d = pathlib.Path(sys.argv[1]); (d / 'cancel.jsonl').write_text({(_row("cancel-final") + chr(10))!r})
time.sleep(30)
"""
    state, worker, sent, sessions = _prompt_thread(shim, monkeypatch, tmp_path, code)
    _wait_until(lambda: (sessions / "cancel.jsonl").exists())
    state.cancel()
    worker.join(3)
    assert not worker.is_alive()
    assert next(m for m in sent if m.get("id") == 3)["result"] == {
        "stopReason": "cancelled"
    }
    update = next(m for m in sent if m.get("method") == "session/update")
    terminal = next(m for m in sent if m.get("id") == 3)
    assert update["params"]["update"]["text"] == "cancel-final"
    assert sent.index(update) < sent.index(terminal)


def test_terminate_escalates_after_leader_exits_and_is_repeatable(
    shim, tmp_path
) -> None:
    child_pid_path = tmp_path / "child-pid"
    child_code = (
        "import os,pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time; subprocess.Popen(sys.argv[1:]); time.sleep(30)",
            sys.executable,
            "-c",
            child_code,
            str(child_pid_path),
        ],
        start_new_session=True,
    )
    try:
        _wait_until(child_pid_path.exists)
        child_pid = int(child_pid_path.read_text())
        shim._terminate_process_group(proc, grace=0.05)

        def child_stopped():
            try:
                return (
                    pathlib.Path(f"/proc/{child_pid}/stat").read_text().split()[2]
                    == "Z"
                )
            except FileNotFoundError:
                return True

        _wait_until(child_stopped)
        assert proc.returncode == -signal.SIGTERM
        shim._terminate_process_group(proc, grace=0.05)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_cancel_before_spawn_is_honored(shim, monkeypatch, tmp_path) -> None:
    state = shim._PromptState()
    token = object()
    assert state.reserve(token)
    state.cancel()
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    shim._run_prompt(
        state,
        token,
        3,
        "s",
        (sys.executable, "-c", "import time; time.sleep(30)"),
        dict(os.environ),
        tmp_path,
        poll_interval=0.01,
    )
    assert next(m for m in sent if m.get("id") == 3)["result"] == {
        "stopReason": "cancelled"
    }


def test_final_drain_and_large_capture_do_not_deadlock(
    shim, monkeypatch, tmp_path
) -> None:
    code = f"""
import json, pathlib, sys
d = pathlib.Path(sys.argv[1]); (d / 'final.jsonl').write_text({(_row("final") + chr(10))!r})
sys.stderr.write('x' * 100000)
print('y' * 100000)
print(json.dumps({{'meta': {{'agentMeta': {{'sessionId': 'final'}}}}}}))
"""
    _, worker, sent, _ = _prompt_thread(shim, monkeypatch, tmp_path, code)
    worker.join(3)
    assert not worker.is_alive()
    assert any(
        m.get("params", {}).get("update", {}).get("text") == "final" for m in sent
    )
    diagnostic = next(
        m
        for m in sent
        if m.get("params", {}).get("update", {}).get("sessionUpdate") == "agent_thought"
    )
    assert len(diagnostic["params"]["update"]["text"]) <= shim._DIAG_TRUNCATE


def test_timeout_drains_update_and_preserves_end_turn(
    shim, monkeypatch, tmp_path
) -> None:
    proc = SimpleNamespace(pid=123, stopped=False)
    proc.poll = lambda: 0 if proc.stopped else None
    proc.wait = lambda timeout=None: 0

    def popen(*args, **kwargs):
        sessions = pathlib.Path(args[0][-1])
        (sessions / "timeout.jsonl").write_text(_row("timeout-final") + "\n")
        return proc

    monkeypatch.setattr(shim.subprocess, "Popen", popen)
    monkeypatch.setattr(
        shim,
        "_terminate_process_group",
        lambda process: setattr(process, "stopped", True),
    )
    monkeypatch.setattr(
        shim,
        "time",
        SimpleNamespace(monotonic=iter([0, 1]).__next__, sleep=lambda _: None),
    )
    _, worker, sent, _ = _prompt_thread(shim, monkeypatch, tmp_path, "", timeout=0.5)
    worker.join(3)
    assert not worker.is_alive()
    update = next(m for m in sent if m.get("method") == "session/update")
    terminal = next(m for m in sent if m.get("id") == 3)
    assert update["params"]["update"]["text"] == "timeout-final"
    assert sent.index(update) < sent.index(terminal)
    assert terminal["result"] == {"stopReason": "end_turn"}


def test_normal_stdout_fallback_is_preserved(shim, monkeypatch, tmp_path) -> None:
    code = "import json; print(json.dumps({'payloads': [{'text': 'fallback'}]}))"
    _, worker, sent, _ = _prompt_thread(shim, monkeypatch, tmp_path, code)
    worker.join(3)
    assert not worker.is_alive()
    assert any(
        m.get("params", {}).get("update", {}).get("text") == "fallback" for m in sent
    )
    assert next(m for m in sent if m.get("id") == 3)["result"] == {
        "stopReason": "end_turn"
    }


def test_prompt_reaps_before_bounded_capture_reads(shim, monkeypatch, tmp_path) -> None:
    proc = SimpleNamespace(pid=123, waited=False, poll=lambda: 0)

    def wait(timeout=None):
        proc.waited = True
        return 0

    proc.wait = wait
    read_limits = []

    class Capture(io.BytesIO):
        def seek(self, offset):
            assert offset == 0
            assert proc.waited
            return super().seek(offset)

        def read(self, limit):
            read_limits.append(limit)
            return super().read(limit)

    captures = iter([Capture(b'{"payloads":[{"text":"ok"}]}'), Capture(b"")])
    monkeypatch.setattr(shim.tempfile, "TemporaryFile", lambda: next(captures))
    monkeypatch.setattr(shim.subprocess, "Popen", lambda *args, **kwargs: proc)
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    state = shim._PromptState()
    token = object()
    assert state.reserve(token)
    shim._run_prompt(state, token, 3, "s", ("openclaw",), {}, tmp_path)
    assert read_limits == [shim._CAPTURE_LIMIT, shim._DIAG_TRUNCATE + 1]
    assert any(m.get("params", {}).get("update", {}).get("text") == "ok" for m in sent)


def test_prompt_spawn_error_is_protocol_error(shim, monkeypatch, tmp_path) -> None:
    state = shim._PromptState()
    token = object()
    assert state.reserve(token)
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    shim._run_prompt(state, token, 3, "s", ("/missing/openclaw",), {}, tmp_path)
    assert next(m for m in sent if m.get("id") == 3)["error"]["code"] == -32603


def test_active_prompt_rejects_mutating_requests(shim, monkeypatch) -> None:
    cancelled = threading.Event()

    def run_prompt(state, token, request_id, *args, **kwargs):
        assert cancelled.wait(2)
        state.finish(token)

    cancel_calls = 0
    original_cancel = shim._PromptState.cancel

    def cancel(state):
        nonlocal cancel_calls
        cancel_calls += 1
        original_cancel(state)
        cancelled.set()

    inbox = iter(
        [
            {"id": 1, "method": "session/prompt", "params": {"prompt": []}},
            {"id": 2, "method": "session/prompt", "params": {"prompt": []}},
            {"id": 3, "method": "session/new", "params": {"cwd": "/tmp"}},
            {"id": 4, "method": "session/set_model", "params": {"modelId": "x"}},
            {"method": "session/cancel", "params": {}},
            {"id": 5, "method": "session/cancel", "params": {}},
        ]
    )
    monkeypatch.setattr(shim, "setup_openai_auth", lambda: None)
    monkeypatch.setattr(shim, "setup_gcloud_adc", lambda: None)

    def recv():
        try:
            return next(inbox)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr(shim, "recv", recv)
    monkeypatch.setattr(shim, "_run_prompt", run_prompt)
    monkeypatch.setattr(shim._PromptState, "cancel", cancel)
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    shim.main()
    assert [
        next(m for m in sent if m.get("id") == i)["error"]["code"] for i in (2, 3, 4)
    ] == [
        -32600,
        -32600,
        -32600,
    ]
    assert next(m for m in sent if m.get("id") == 5)["result"] == {}
    assert not any(m.get("id", object()) is None for m in sent)
    assert cancel_calls == 3  # notification, request, EOF cleanup
    assert cancelled.is_set()

"""Agents-owned unit coverage for canonical OpenClaw ACP shim."""

from __future__ import annotations

import json
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

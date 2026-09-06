"""Load canonical OpenClaw shim directly; BenchFlow need not be installed."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def clean_shim_env(monkeypatch):
    """Prevent host credentials/config from affecting direct shim tests."""
    for name in (
        "OPENAI_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_APPLICATION_CREDENTIALS_JSON",
        "BENCHFLOW_PROVIDER_NAME",
        "BENCHFLOW_PROVIDER_BASE_URL",
        "BENCHFLOW_PROVIDER_API_KEY",
        "BENCHFLOW_PROVIDER_PROTOCOL",
        "BENCHFLOW_PROVIDER_MODELS",
        "BENCHFLOW_MODEL_TEMPERATURE",
        "BENCHFLOW_MODEL_TOP_P",
        "BENCHFLOW_MODEL_MAX_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def shim(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "openclaw_acp_shim.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("openclaw_acp_shim_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_providers(monkeypatch):
    """Install minimal provider registry seam used by copied shim tests."""
    benchflow = types.ModuleType("benchflow")
    agents = types.ModuleType("benchflow.agents")
    providers = types.ModuleType("benchflow.agents.providers")
    providers.find_provider = lambda _model: None
    providers.find_provider_for_bare_model = lambda _model: None

    def resolve_base_url(config, env):
        if config.url_env:
            return env[config.url_env]
        return config.base_url

    providers.resolve_base_url = resolve_base_url
    monkeypatch.setitem(sys.modules, "benchflow", benchflow)
    monkeypatch.setitem(sys.modules, "benchflow.agents", agents)
    monkeypatch.setitem(sys.modules, "benchflow.agents.providers", providers)
    return providers

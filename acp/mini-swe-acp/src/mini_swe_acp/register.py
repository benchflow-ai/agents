"""Register mini-swe-agent with BenchFlow via the public ``register_agent`` API.

This is the out-of-core equivalent of the entry in benchflow's own
``agents/registry.py``: same install/launch commands, same provider wiring, but
defined through the supported extension point so the integration lives in this
repo instead of the framework. The ACP shim is shipped alongside (``acp_shim.py``)
and base64-deployed into the sandbox by the install command.
"""

import base64
import inspect
from pathlib import Path

from benchflow.agents.registry import (
    AGENT_ALIASES,
    _apt_install,
    _BENCHFLOW_BIN_PREFIX,
    _install_python_script,
    register_agent,
)

# Isolated venv for the Python-based mini-swe-agent harness — kept out of the
# task's own Python so benchmark images can pin whatever interpreter they need.
_MINI_SWE_VENV = "/opt/benchflow/mini-swe-venv"
_SHIM_SOURCE = (Path(__file__).parent / "acp_shim.py").read_text()
_SHIM_PATH = f"{_BENCHFLOW_BIN_PREFIX}/mini-swe-acp-shim"

# The venv's packages, every one at an exact version (requirements.txt says how
# it is compiled). The install used to be a bare ``pip install mini-swe-agent``,
# so each trial took whatever was newest: LiteLLM 1.106.0 (2026-10-18) made every
# trial fail, because its ``completion()`` imports its MCP gateway module
# (``litellm.proxy._experimental.mcp_server.catalog`` -> ``mcp.types``) whenever
# ``tools`` is non-empty, and ``mcp`` ships only in LiteLLM's proxy/mcp extras.
# mini-swe always sends its bash tool, so each model call raised
# ModuleNotFoundError and mini-swe retried it for ~17 minutes per trial.
MINI_SWE_AGENT_VERSION = "2.4.6"
LITELLM_VERSION = "1.105.1"
PIP_VERSION = "26.2.1"
_REQUIREMENTS_SOURCE = (Path(__file__).parent / "requirements.txt").read_text()
_REQUIREMENTS_PATH = "/opt/benchflow/mini-swe-requirements.txt"

# Run once after the install: the call mini-swe makes on every step (a
# completion with a tool), answered by LiteLLM's mock_response so it needs no
# network or key. A dependency that only that call path imports fails here, at
# setup, instead of in each model call of the trial.
_TOOL_CALL_PROBE = (
    "import minisweagent.models.litellm_model, litellm; "
    "litellm.completion(model='openai/install-probe', "
    "messages=[{'role': 'user', 'content': 'probe'}], "
    "tools=[{'type': 'function', 'function': {'name': 'bash', "
    "'parameters': {'type': 'object', 'properties': {}}}}], "
    "mock_response='ok')"
)

_ALIASES = ("mini", "minisweagent", "mini-swe-agent")


def _write_file(container_path: str, text: str) -> str:
    """Shell snippet that writes ``text`` to ``container_path`` (base64, so the
    content never meets shell quoting)."""
    encoded = base64.b64encode(text.encode()).decode()
    return f"echo {encoded} | base64 -d > {container_path}"


def _install_cmd() -> str:
    python = f"{_MINI_SWE_VENV}/bin/python"
    return (
        "export DEBIAN_FRONTEND=noninteractive && "
        "( command -v python3 >/dev/null 2>&1 || "
        f"  {_apt_install('python3', 'python3-venv', 'python3-pip')} ) && "
        f"( [ -x {python} ] || "
        f"  python3 -m venv {_MINI_SWE_VENV} || "
        f"  ( {_apt_install('python3-venv')} && "
        f"    python3 -m venv {_MINI_SWE_VENV} ) ) && "
        f"{python} -m pip install -q pip=={PIP_VERSION} && "
        "mkdir -p /opt/benchflow && "
        f"{_write_file(_REQUIREMENTS_PATH, _REQUIREMENTS_SOURCE)} && "
        f"{python} -m pip install -q -r {_REQUIREMENTS_PATH} && "
        + _install_python_script(_SHIM_PATH, _SHIM_SOURCE)
        + " && chmod -R a+rX /opt/benchflow && "
        "cd / && MSWEA_SILENT_STARTUP=1 LITELLM_LOCAL_MODEL_COST_MAP=True "
        f'{python} -I -c "{_TOOL_CALL_PROBE}" >/dev/null'
    )


def _launch_cmd() -> str:
    return (
        "MSWEA_SILENT_STARTUP=1 MSWEA_COST_TRACKING=ignore_errors "
        f"{_MINI_SWE_VENV}/bin/python {_SHIM_PATH}"
    )


def _cache_kwargs() -> dict[str, str]:
    """Mark the install as pinned where BenchFlow can cache it.

    Every package is pinned (requirements.txt), so BenchFlow releases whose
    ``register_agent`` takes ``cacheable_version`` build the install once into
    a cached image layer per task image and reuse it, instead of installing in
    every trial. Older releases install in every trial, as before.
    """
    if "cacheable_version" not in inspect.signature(register_agent).parameters:
        return {}
    version = f"{MINI_SWE_AGENT_VERSION}+litellm-{LITELLM_VERSION}"
    return {"cacheable_version": version}


def register() -> None:
    """Register the ``mini-swe`` agent (and its aliases) into BenchFlow."""
    register_agent(
        name="mini-swe",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        # Inferred from --model at runtime; the shim reads BENCHFLOW_PROVIDER_*.
        requires_env=[],
        # Empty lets the provider determine routing for multi-endpoint providers;
        # the shim reconstructs the litellm prefix from BENCHFLOW_PROVIDER_PROTOCOL.
        api_protocol="",
        description=(
            "mini-swe-agent via ACP shim — minimal single-bash-tool harness "
            "(multi-model via litellm)"
        ),
        **_cache_kwargs(),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "mini-swe")

"""Register mini-swe-agent with BenchFlow via the public ``register_agent`` API.

This is the out-of-core equivalent of the entry in benchflow's own
``agents/registry.py``: same install/launch commands, same provider wiring, but
defined through the supported extension point so the integration lives in this
repo instead of the framework. The ACP shim is shipped alongside (``acp_shim.py``)
and base64-deployed into the sandbox by the install command.
"""

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

_ALIASES = ("mini", "minisweagent", "mini-swe-agent")


def _install_cmd() -> str:
    return (
        "export DEBIAN_FRONTEND=noninteractive && "
        "( command -v python3 >/dev/null 2>&1 || "
        f"  {_apt_install('python3', 'python3-venv', 'python3-pip')} ) && "
        f"( [ -x {_MINI_SWE_VENV}/bin/python ] || "
        f"  python3 -m venv {_MINI_SWE_VENV} || "
        f"  ( {_apt_install('python3-venv')} && "
        f"    python3 -m venv {_MINI_SWE_VENV} ) ) && "
        f"{_MINI_SWE_VENV}/bin/python -m pip install -q --upgrade pip && "
        f"{_MINI_SWE_VENV}/bin/python -m pip install -q mini-swe-agent && "
        + _install_python_script(_SHIM_PATH, _SHIM_SOURCE)
        + " && chmod -R a+rX /opt/benchflow && "
        f"{_MINI_SWE_VENV}/bin/python -c 'import minisweagent'"
    )


def _launch_cmd() -> str:
    return (
        "MSWEA_SILENT_STARTUP=1 MSWEA_COST_TRACKING=ignore_errors "
        f"{_MINI_SWE_VENV}/bin/python {_SHIM_PATH}"
    )


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
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "mini-swe")

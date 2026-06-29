"""Register the Vercel AI SDK 7 HarnessAgent (DeepAgents harness) with BenchFlow.

Out-of-core equivalent of a benchflow registry entry. A pure-JS ACP-over-stdio
server (``server.mjs``) wraps the AI SDK 7 ``HarnessAgent`` running the
**DeepAgents** harness. deepagents is a JS agent loop, so — like Pi — it runs
**in-process** on the local ``@ai-sdk/sandbox-just-bash`` sandbox (no port-exposing
bridge), inside benchflow's task sandbox on the real task files.

STATUS: scaffolded/listed. This installs the harness package and wires the agent
into benchflow's registry; the server installs, parses, and streams over ACP. The
model routing + wire-parity are **NOT yet verified** (next step).

NOTE: deepagents also exists as a benchflow-native ACP agent (``deepagents``);
this package is the AI-SDK-harness variant of the same agent loop.
"""

import base64
from pathlib import Path

from benchflow.agents.registry import (
    AGENT_ALIASES,
    _BENCHFLOW_NODE_PREFIX,
    _NODE_INSTALL,
    register_agent,
)

_PREFIX = "/opt/benchflow/js-agents/ai-sdk-deepagents"
_SERVER_SOURCE = (Path(__file__).parent / "server.mjs").read_text()
_DEPS = (
    "@ai-sdk/harness@1.0.6",
    "@ai-sdk/harness-deepagents@1.0.5",
    "@ai-sdk/sandbox-just-bash@1.0.6",
    "just-bash",
)
_ALIASES = ("ai-sdk-deepagents-harness", "deepagents-harness")


def _install_cmd() -> str:
    b64 = base64.b64encode(_SERVER_SOURCE.encode()).decode()
    pkg = '{"name":"bf-ai-sdk-deepagents","private":true,"type":"module"}'
    return (
        f"{_NODE_INSTALL} && mkdir -p {_PREFIX} && "
        f"printf '%s' '{b64}' | base64 -d > {_PREFIX}/server.mjs && "
        f"printf '%s' '{pkg}' > {_PREFIX}/package.json && cd {_PREFIX} && "
        f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install {' '.join(_DEPS)} "
        f"--no-audit --no-fund >/dev/null 2>&1 && "
        f"[ -f {_PREFIX}/server.mjs ] && [ -d {_PREFIX}/node_modules/@ai-sdk/harness ]"
    )


def _launch_cmd() -> str:
    return (
        "env -u NODE_OPTIONS -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy "
        "-u NO_PROXY -u no_proxy -u NODE_TLS_REJECT_UNAUTHORIZED "
        f"{_BENCHFLOW_NODE_PREFIX}/bin/node {_PREFIX}/server.mjs"
    )


def register() -> None:
    """Register the ``ai-sdk-deepagents`` agent (and aliases) into BenchFlow."""
    register_agent(
        name="ai-sdk-deepagents",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        # TODO(next step): verify harness-deepagents's real provider env slot +
        # whether usage_tracking must be off. This OPENAI_* mapping is a best-effort
        # default (deepagents is OpenAI-compatible chat-completions); the server reads
        # OPENROUTER_*||OPENAI_* and feeds the harness's customEnv — unverified.
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        acp_model_format="bare",
        supports_acp_set_model=True,
        requires_env=[],
        install_timeout=1200,  # harness + deepagents install is heavy
        description=(
            "Vercel AI SDK 7 HarnessAgent (DeepAgents harness + just-bash local "
            "sandbox) via ACP — scaffolded/listed; model routing + parity not yet "
            "verified (next step)"
        ),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "ai-sdk-deepagents")

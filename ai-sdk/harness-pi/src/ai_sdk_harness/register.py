"""Register the Vercel AI SDK 7 HarnessAgent (Pi harness) with BenchFlow.

Out-of-core equivalent of a benchflow registry entry. A pure-JS ACP-over-stdio
server (``server.mjs``) wraps the AI SDK 7 ``HarnessAgent`` running the **Pi**
harness on the local ``@ai-sdk/sandbox-just-bash`` sandbox, so the harness runs
*inside* benchflow's task sandbox on the real task files.

IMPORTANT — run with ``usage_tracking="off"`` (see README): Pi mangles the
LiteLLM proxy's model alias and falls back to its own default model, so the
proxy must be bypassed. The agent then gets the raw provider creds + bare model
id, and usage is captured natively via ``agent_native_acp`` (Pi's
``finish.totalUsage`` -> ACP ``PromptResult.usage``).

Only the **Pi** harness works here: claude-code/codex are bridge-backed and
require a port-exposing (Vercel) sandbox that the local just-bash sandbox
rejects — and benchflow already runs those natively via claude-agent-acp /
codex-acp.
"""

import base64
from pathlib import Path

from benchflow.agents.registry import (
    AGENT_ALIASES,
    _BENCHFLOW_NODE_PREFIX,
    _NODE_INSTALL,
    register_agent,
)

_PREFIX = "/opt/benchflow/js-agents/ai-sdk-harness"
_SERVER_SOURCE = (Path(__file__).parent / "server.mjs").read_text()
# Experimental/canary AI SDK 7 harness packages.
_DEPS = (
    "@ai-sdk/harness@canary",
    "@ai-sdk/harness-pi@canary",
    "@ai-sdk/sandbox-just-bash@canary",
    "just-bash",
)
_ALIASES = ("ai-sdk-pi", "pi-harness")


def _install_cmd() -> str:
    b64 = base64.b64encode(_SERVER_SOURCE.encode()).decode()
    pkg = '{"name":"bf-ai-sdk-harness","private":true,"type":"module"}'
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
    """Register the ``ai-sdk-harness`` agent (and aliases) into BenchFlow."""
    register_agent(
        name="ai-sdk-harness",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        # openai-completions: Pi's openrouter slot speaks chat-completions; the
        # provider base/key are handed to it as OPENROUTER_* (run usage_tracking=off
        # so these are the raw provider creds, not the proxy's — see README).
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENROUTER_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENROUTER_API_KEY",
        },
        acp_model_format="bare",
        supports_acp_set_model=True,
        requires_env=[],
        install_timeout=1200,  # canary harness + pi-coding-agent install is heavy
        description=(
            "Vercel AI SDK 7 HarnessAgent (Pi harness + just-bash local sandbox) "
            "via ACP — experimental/canary; run with usage_tracking=off"
        ),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "ai-sdk-harness")

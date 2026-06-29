"""Register the Vercel AI SDK 7 HarnessAgent (OpenCode harness) with BenchFlow.

Out-of-core equivalent of a benchflow registry entry. A pure-JS ACP-over-stdio
server (``server.mjs``) wraps the AI SDK 7 ``HarnessAgent`` running the
**OpenCode** harness (``@ai-sdk/harness-opencode``).

UNVERIFIED execution model: unlike Pi (in-process on the local just-bash
sandbox), opencode bridges out to a separate ``opencode`` process. So whether
this runs in-process on ``@ai-sdk/sandbox-just-bash`` or needs a bridge sandbox
(like codex/claude-code's Vercel sandbox) is NOT yet established — it must be
verified in the next step. We keep the just-bash template from ``harness-pi`` for
now (and say so here) rather than guess at a bridge sandbox.

STATUS: scaffolded / listed — installs the harness package and registers the
agent; model routing + wire-parity are NOT yet verified (next step). The provider
env slot below is a best-effort default copied from the chat-completions
template; see the TODO on ``env_mapping``.

NOTE: opencode also exists as a benchflow-native ACP agent (``opencode``); this
package is the AI-SDK-``HarnessAgent`` variant of it, not a replacement.
"""

import base64
from pathlib import Path

from benchflow.agents.registry import (
    AGENT_ALIASES,
    _BENCHFLOW_NODE_PREFIX,
    _NODE_INSTALL,
    register_agent,
)

_PREFIX = "/opt/benchflow/js-agents/ai-sdk-opencode"
_SERVER_SOURCE = (Path(__file__).parent / "server.mjs").read_text()
# Pinned AI SDK 7 harness packages (kept on the just-bash template for now —
# the real execution model is unverified; see module docstring).
_DEPS = (
    "@ai-sdk/harness@1.0.6",
    "@ai-sdk/harness-opencode@1.0.6",
    "@ai-sdk/sandbox-just-bash@1.0.6",
    "just-bash",
)
_ALIASES = ("ai-sdk-opencode-harness", "opencode-harness")


def _install_cmd() -> str:
    b64 = base64.b64encode(_SERVER_SOURCE.encode()).decode()
    pkg = '{"name":"bf-ai-sdk-opencode","private":true,"type":"module"}'
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
    """Register the ``ai-sdk-opencode`` agent (and aliases) into BenchFlow."""
    register_agent(
        name="ai-sdk-opencode",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        api_protocol="openai-completions",
        # TODO(next step): verify harness-opencode's real provider env slot +
        # whether usage_tracking must be off. This is a best-effort default
        # (OpenAI-compatible chat-completions slot); not yet confirmed.
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        acp_model_format="bare",
        supports_acp_set_model=True,
        requires_env=[],
        install_timeout=1200,  # AI SDK 7 harness + opencode install is heavy
        description=(
            "Vercel AI SDK 7 HarnessAgent (OpenCode harness) via ACP — scaffolded; "
            "installs @ai-sdk/harness-opencode; model routing + parity NOT yet "
            "verified (next step). AI-SDK-harness variant of the native opencode agent"
        ),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "ai-sdk-opencode")

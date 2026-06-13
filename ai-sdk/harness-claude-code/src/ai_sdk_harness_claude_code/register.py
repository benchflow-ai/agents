"""Register the Vercel AI SDK 7 HarnessAgent (Claude Code harness) with BenchFlow.

⚠️ EXPERIMENTAL / does NOT run as a benchflow eval. The Claude Code harness is
bridge-backed and requires a port-exposing Vercel sandbox (`@ai-sdk/sandbox-vercel`
+ Vercel creds) — which is remote, so the agent's files never reach benchflow's
task `/app` and the verifier can't see them. The local just-bash sandbox rejects
bridge-backed harnesses. For real benchflow evaluation of Claude Code, use the native
`claude-agent-acp` agent. Shipped for completeness / as a Vercel-sandbox template.
"""

import base64
from pathlib import Path

from benchflow.agents.registry import (
    AGENT_ALIASES,
    _BENCHFLOW_NODE_PREFIX,
    _NODE_INSTALL,
    register_agent,
)

_PREFIX = "/opt/benchflow/js-agents/ai-sdk-claude-code"
_SERVER_SOURCE = (Path(__file__).parent / "server.mjs").read_text()
_DEPS = ("@ai-sdk/harness@canary", "@ai-sdk/harness-claude-code@canary", "@ai-sdk/sandbox-vercel@canary")
_ALIASES = ("ai-sdk-claude-code-harness",)


def _install_cmd() -> str:
    b64 = base64.b64encode(_SERVER_SOURCE.encode()).decode()
    pkg = '{"name":"bf-ai-sdk-claude-code","private":true,"type":"module"}'
    return (
        f"{_NODE_INSTALL} && mkdir -p {_PREFIX} && "
        f"printf '%s' '{b64}' | base64 -d > {_PREFIX}/server.mjs && "
        f"printf '%s' '{pkg}' > {_PREFIX}/package.json && cd {_PREFIX} && "
        f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install {' '.join(_DEPS)} --no-audit --no-fund >/dev/null 2>&1 && "
        f"[ -d {_PREFIX}/node_modules/@ai-sdk/harness ]"
    )


def _launch_cmd() -> str:
    return f"{_BENCHFLOW_NODE_PREFIX}/bin/node {_PREFIX}/server.mjs"


def register() -> None:
    """Register the ``ai-sdk-claude-code`` agent. NOTE: needs a Vercel sandbox to run."""
    register_agent(
        name="ai-sdk-claude-code",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        api_protocol="anthropic-messages",  # Claude Code speaks the Anthropic Messages API
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "ANTHROPIC_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "ANTHROPIC_API_KEY",
        },
        acp_model_format="bare",
        supports_acp_set_model=True,
        requires_env=[],
        install_timeout=1200,
        description=(
            "Vercel AI SDK 7 HarnessAgent (Claude Code) — EXPERIMENTAL; requires a Vercel "
            "sandbox, does NOT run on benchflow's local sandbox (use claude-agent-acp)"
        ),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "ai-sdk-claude-code")

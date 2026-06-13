"""Register the Vercel AI SDK agent with BenchFlow via the public ``register_agent`` API.

Out-of-core equivalent of an entry in benchflow's own ``agents/registry.py``: a
pure-JS ACP-over-stdio server (``server.mjs``) wrapping a Vercel AI SDK
``ToolLoopAgent``. The server is base64-deployed into the sandbox by the install
command; its model calls route through BenchFlow's gateway (``OPENAI_BASE_URL``),
so usage is captured and the benchmark's model is enforced.

The agent is hardened for inside==outside behavioral parity (see ``server.mjs``):
env-independent system prompt, latent proxy/TLS env scrubbed, and a tool-execution
keepalive that feeds BenchFlow's idle watchdog during long tools.
"""

import base64
from pathlib import Path

from benchflow.agents.registry import (
    AGENT_ALIASES,
    _BENCHFLOW_NODE_PREFIX,
    _NODE_INSTALL,
    register_agent,
)

# Isolated prefix so the agent's Node/deps stay out of the task image's own runtime.
_PREFIX = "/opt/benchflow/js-agents/ai-sdk"
_SERVER_SOURCE = (Path(__file__).parent / "server.mjs").read_text()

# Pinned to the versions the agent + parity suite were validated against.
_DEPS = ("ai@6.0.204", "@ai-sdk/openai-compatible@2.0.50", "zod@4.4.3")
_ALIASES = ("aisdk", "vercel-ai-sdk")


def _install_cmd() -> str:
    """Bootstrap Node, base64-deploy server.mjs, and install pinned AI SDK deps."""
    b64 = base64.b64encode(_SERVER_SOURCE.encode()).decode()
    pkg = '{"name":"bf-ai-sdk","private":true,"type":"module"}'
    return (
        f"{_NODE_INSTALL} && mkdir -p {_PREFIX} && "
        f"printf '%s' '{b64}' | base64 -d > {_PREFIX}/server.mjs && "
        f"printf '%s' '{pkg}' > {_PREFIX}/package.json && cd {_PREFIX} && "
        f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install {' '.join(_DEPS)} "
        f"--no-audit --no-fund >/dev/null 2>&1 && "
        f"[ -f {_PREFIX}/server.mjs ] && [ -d {_PREFIX}/node_modules/ai ]"
    )


def _launch_cmd() -> str:
    """Launch via the private Node, scrubbing latent env for inside/outside parity.

    NODE_OPTIONS must be stripped before Node starts (server.mjs additionally
    deletes proxy/TLS vars in-process for request-time fetch behavior).
    """
    return (
        "env -u NODE_OPTIONS -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy "
        "-u NO_PROXY -u no_proxy -u NODE_TLS_REJECT_UNAUTHORIZED "
        f"{_BENCHFLOW_NODE_PREFIX}/bin/node {_PREFIX}/server.mjs"
    )


def register() -> None:
    """Register the ``ai-sdk`` agent (and its aliases) into BenchFlow."""
    register_agent(
        name="ai-sdk",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        # openai-completions matches DeepSeek + any OpenAI-compatible provider the
        # gateway exposes; unlike codex's hard openai-responses lock, the AI SDK
        # provider can speak whatever the route offers.
        api_protocol="openai-completions",
        # Generic env_mapping path → the LiteLLM gateway URL lands in OPENAI_BASE_URL
        # and the proxy master key in OPENAI_API_KEY (and usage is captured because
        # ai-sdk is NOT in _NATIVE_PROTOCOL_AGENTS).
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        # modelId arrives bare (the proxy alias) via session/set_model; the server
        # forwards it straight to the provider, so there is no opaque model registry.
        acp_model_format="bare",
        supports_acp_set_model=True,
        # Required key is inferred from --model (e.g. DEEPSEEK_API_KEY); the agent
        # itself only ever sees the proxy master key.
        requires_env=[],
        description=(
            "Vercel AI SDK ToolLoopAgent via pure-JS ACP server "
            "(OpenAI-compatible gateway routing; usage via includeUsage)"
        ),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "ai-sdk")

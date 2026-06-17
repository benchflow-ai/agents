"""Register the Vercel AI SDK 7 HarnessAgent (MiMo harness) with BenchFlow.

A pure-JS ACP-over-stdio server (``server.mjs``) wraps the AI SDK 7
``HarnessAgent`` running a thin custom HarnessV1 adapter (``createMimo``) that
drives MiMo Code's NATIVE ``mimo acp`` server — spawned on the host so its stdin
is writable for ACP JSON-RPC (the harness sandbox's SandboxProcess has none).
Unlike ``harness-pi``/``-codex``/``-claude-code`` there is no vendor
``@ai-sdk/harness-<x>`` package and no JS-library agent loop: MiMo *is* the ACP
agent, so the adapter only bridges its protocol into the AI SDK stream.

Both usage modes work (see README). In **proxy mode** (``usage_tracking`` auto/
required, the default) benchflow points ``OPENAI_BASE_URL`` at its LiteLLM usage
proxy and passes a ``benchflow-*`` model alias; MiMo (an OpenCode fork) would
reject an unknown alias via ``models.dev``, so ``createMimoSession`` writes a
per-session ``.mimocode/mimocode.json`` registering an OpenAI-compatible custom
provider ``benchflow`` at the proxy and sets the inner model to
``benchflow/<alias>`` — the turn routes THROUGH the proxy, which captures the raw
LLM trajectory and reports ``usage_source=provider_response``. In **usage-off
mode** no proxy is set, so MiMo gets the raw provider creds + bare model id and
usage is captured natively via the ACP ``PromptResult.usage``; the free
``mimo/mimo-auto`` model needs no key.
"""

import base64
from pathlib import Path

from benchflow.agents.registry import (
    AGENT_ALIASES,
    _BENCHFLOW_NODE_PREFIX,
    _NODE_INSTALL,
    register_agent,
)

_PREFIX = "/opt/benchflow/js-agents/ai-sdk-mimo"
_SERVER_SOURCE = (Path(__file__).parent / "server.mjs").read_text()
# @ai-sdk/harness pulls `ai`; @mimo-ai/cli provides the native `mimo` binary +
# `mimo acp`. No @ai-sdk/harness-<x> (no vendor harness) and no sandbox lib
# (the adapter ships its own host-fs HarnessV1SandboxProvider).
# @ai-sdk/harness is published ONLY under the `canary` dist-tag (no stable
# release yet); pin an EXACT canary version for reproducible installs rather
# than the floating `@canary` tag (which would silently move). @mimo-ai/cli is
# standardized at @0.1.1 across the agents-repo MiMo packages.
_AI_SDK_HARNESS = "@ai-sdk/harness@1.0.0-canary.13"
_DEPS = (_AI_SDK_HARNESS, "@mimo-ai/cli@0.1.1")
_ALIASES = ("ai-sdk-harness-mimo", "mimo-harness")


def _install_cmd() -> str:
    b64 = base64.b64encode(_SERVER_SOURCE.encode()).decode()
    pkg = '{"name":"bf-ai-sdk-mimo","private":true,"type":"module"}'
    return (
        f"{_NODE_INSTALL} && mkdir -p {_PREFIX} && "
        f"printf '%s' '{b64}' | base64 -d > {_PREFIX}/server.mjs && "
        f"printf '%s' '{pkg}' > {_PREFIX}/package.json && cd {_PREFIX} && "
        f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install {' '.join(_DEPS)} "
        f"--no-audit --no-fund >/dev/null 2>&1 && "
        f"[ -f {_PREFIX}/server.mjs ] && [ -x {_PREFIX}/node_modules/.bin/mimo ] && "
        f"[ -d {_PREFIX}/node_modules/@ai-sdk/harness ]"
    )


def _launch_cmd() -> str:
    # Strip latent proxy/TLS env for inside/outside parity (server.mjs also
    # deletes them in-process); MIMO_BIN points the adapter at the pinned CLI.
    return (
        "env -u NODE_OPTIONS -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy "
        "-u NO_PROXY -u no_proxy -u NODE_TLS_REJECT_UNAUTHORIZED "
        f"MIMO_BIN={_PREFIX}/node_modules/.bin/mimo "
        f"{_BENCHFLOW_NODE_PREFIX}/bin/node {_PREFIX}/server.mjs"
    )


def register() -> None:
    """Register the ``ai-sdk-mimo`` agent (and aliases) into BenchFlow."""
    register_agent(
        name="ai-sdk-mimo",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        acp_model_format="bare",
        supports_acp_set_model=True,
        requires_env=[],
        install_timeout=1200,
        description=(
            "Vercel AI SDK 7 HarnessAgent driving MiMo Code's native `mimo acp` "
            "(OpenCode fork) — thin custom HarnessV1 adapter, no server.mjs-side "
            "agent loop; proxy mode (default) routes through the LiteLLM usage "
            "proxy via a custom provider (provider_response usage); usage_tracking="
            "off uses native ACP usage (free mimo/mimo-auto needs no key)"
        ),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "ai-sdk-mimo")

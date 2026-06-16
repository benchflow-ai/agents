"""Register MiMo Code with BenchFlow via the public ``register_agent`` API.

Out-of-core equivalent of an entry in benchflow's own ``agents/registry.py``:
same install/launch wiring, but defined through the supported extension point so
the integration lives in this repo. MiMo Code is an OpenCode fork whose ``mimo``
CLI ships a **native** ``mimo acp`` JSON-RPC-over-stdio ACP server — so, unlike
the ai-sdk ``HarnessAgent`` packages (which implement the ACP server in a JS
``server.mjs`` wrapping an AI-SDK agent), this package deploys **no** server.mjs:
``mimo acp`` *is* the server. Structurally this mirrors ``mini-swe-acp`` (a
native agent registered out-of-core), minus the custom Python ACP shim.

Gotcha: MiMo's ACP ``initialize`` reports ``agentInfo.name="OpenCode"`` (the
upstream fork name). The BenchFlow-side agent name is ``mimo`` (the registry
key) and is independent of that wire value — tests/docs must not conflate them.

Models: this package's validated path is the free **``mimo/mimo-auto``** channel
(no key, headless) — its bare id has no registered provider, so it survives
``set_model`` unchanged and reaches MiMo's native models.dev catalog. The
flagship **``xiaomi/mimo-v2.5-pro``** is best run via the *native ``mimo`` agent
in benchflow core* (which sets ``acp_model_format="provider/model"`` + a
``mimocode.json`` credential file): this out-of-core package deliberately uses
``acp_model_format="bare"`` (required so ``mimo/mimo-auto`` passes through), and
``bare`` strips the ``xiaomi/`` provider prefix — so the native-xiaomi path is
NOT reliably routable here. See benchflow PR #679 for the flagship route.
"""

from benchflow.agents.registry import (
    AGENT_ALIASES,
    _BENCHFLOW_NODE_PREFIX,
    _NODE_INSTALL,
    register_agent,
)

# Isolated prefix so MiMo's Node/deps stay out of the task image's own runtime.
_PREFIX = "/opt/benchflow/js-agents/mimo-acp"
_MIMO_PKG = "@mimo-ai/cli@0.1.1"  # pinned: an unpinned float can break ACP on upgrade
# NOTE: the agents-repo MiMo packages (mimo-acp, ai-sdk-mimo, omnigent-mimo) all
# standardize on @0.1.1 — the live-validated current release (newer than the
# benchflow-core native `mimo` agent's @0.1.0; PR #679, which can bump separately).
_MIMO_BIN = f"{_PREFIX}/node_modules/@mimo-ai/cli/bin/mimo"
_ALIASES = ("mimo-code",)


def _install_cmd() -> str:
    """Bootstrap Node and install the pinned MiMo CLI into the isolated prefix."""
    pkg = '{"name":"bf-mimo-acp","private":true,"type":"module"}'
    return (
        f"{_NODE_INSTALL} && mkdir -p {_PREFIX} && "
        f"printf '%s' '{pkg}' > {_PREFIX}/package.json && cd {_PREFIX} && "
        f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install {_MIMO_PKG} "
        f"--no-audit --no-fund >/dev/null 2>&1 && "
        f"chmod -R a+rX /opt/benchflow && [ -f {_MIMO_BIN} ]"
    )


def _launch_cmd() -> str:
    """Launch MiMo's native ACP server via the private Node."""
    return f"{_BENCHFLOW_NODE_PREFIX}/bin/node {_MIMO_BIN} acp"


def register() -> None:
    """Register the ``mimo`` agent (and its aliases) into BenchFlow."""
    register_agent(
        name="mimo",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        # The free mimo/mimo-auto channel needs no key. Usage-capture for any
        # gateway-routed model lands in OPENAI_BASE_URL/OPENAI_API_KEY.
        api_protocol="openai-completions",
        # Generic gateway routing: the LiteLLM gateway URL + proxy master key land
        # in OPENAI_BASE_URL/OPENAI_API_KEY (usage captured — mimo is not a native
        # provider agent). Same contract as ai-sdk/acp.
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        # modelId arrives bare via session/set_model; the OpenCode-fork forwards
        # it to MiMo's native catalog. "bare" is required so mimo/mimo-auto (no
        # registered provider) passes through unchanged; the trade-off is that a
        # provider-prefixed flagship id (xiaomi/...) gets its prefix stripped, so
        # the native-xiaomi route belongs to the benchflow-core `mimo` agent.
        acp_model_format="bare",
        supports_acp_set_model=True,
        # Free mimo-auto needs no key.
        requires_env=[],
        install_timeout=1200,  # node bootstrap + npm install is heavy
        description=(
            "MiMo Code (Xiaomi, OpenCode fork) native `mimo acp` ACP server "
            "via the `mimo` CLI — no server.mjs (mimo is the ACP server)"
        ),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "mimo")

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

PROXY MODE (this instrumented build, the validated path): to capture wire-level
raw LLM (trajectory/llm_trajectory.jsonl) the agent's model calls must traverse
BenchFlow's LiteLLM usage proxy. BenchFlow drives model selection over the
standard ACP ``session/set_model`` request and, with
``acp_model_format='provider/model'`` + the proxy alias
``benchflow-deepseek-deepseek-v4-flash``, sends ``openai/<alias>`` (see
benchflow ``acp/runtime.py::_format_acp_model`` — it emits the ``openai/``
prefix for every ``benchflow-*`` alias). So the launcher must register a custom
OpenAI-compatible provider under the key ``openai`` that points at the proxy
(``$OPENAI_BASE_URL``) AND carries a ``models`` map keyed EXACTLY by the bare
alias — otherwise mimo throws ``ProviderModelNotFoundError`` and the turn ends
with zero LLM requests (the pr8-proxy5..8 failure signature). The config is
written to ``{home}/.config/mimocode/mimocode.json`` (the canonical location
MiMo Code reads, matching benchflow-core's native ``mimo`` agent) and also to
``./mimocode.json`` so routing is not cwd-dependent. Because mimo's built-in
``openai`` provider auto-activates from ``OPENAI_*`` env and then conflicts with
the redefine (silent 0-token turn), the launcher unsets
``OPENAI_BASE_URL``/``OPENAI_API_KEY`` *after* baking them into the config. As a
fail-fast guard, if ``OPENAI_BASE_URL`` is set but the alias is empty the
launcher aborts (rc 78) instead of emitting a silent zero-LLM turn.

This raw-LLM capture via the proxy is THIS package's validated result (a fresh
Daytona eval of ``deepseek/deepseek-v4-flash`` lands reward 1.0, 7 tool calls,
``usage_source=provider_response`` with multiple MiMoCode agent-turns). The free
key-free ``mimo/mimo-auto`` channel also works in-sandbox but routes to MiMo's
backend (no proxy, no trajectory).

When ``BF_PR8_DEBUG`` is set, the launcher also emits ``BF_DIAG`` lines to
STDOUT before ``exec``-ing mimo; benchflow's ContainerTransport routes any
non-JSON-RPC stdout line into the host-synced ``agent/mimo.txt``, the only
launch-time channel that survives a Daytona run. Secrets (apiKey, URL userinfo)
are redacted in the dump. The diagnostic is gated so production runs stay quiet;
the routing fix (custom ``openai`` provider write + ``unset`` of the colliding
``OPENAI_*`` env) is unconditional.
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
# NOTE: this manifest pins @0.1.1 — the live-validated current release (newer than
# the benchflow-core native `mimo` agent's @0.1.0; PR #679, which can bump separately).
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
    """Launch MiMo's native ACP server, writing the proxy mimocode.json first.

    Returns a base64-embedded launcher of the form
    ``printf '%s' '<b64>' | base64 -d > /tmp/mimo-acp-launch.sh && sh /tmp/...``.

    The base64 indirection is REQUIRED (not cosmetic): benchflow's non-docker
    which-rewrite (acp/runtime.py ~L448) does ``agent_launch.split()`` then
    ``" ".join(...)`` to substitute the resolved path of token 0. That collapses
    every whitespace run to a single space and discards shell quoting — so a
    ``sh -c '<multi-line body>'`` launch_cmd is shredded into a syntax error
    (observed: rc=2, empty agent/mimo.txt). A printf|base64 pipeline survives
    because the base64 payload contains no spaces and the surrounding tokens have
    no internal whitespace, so split()/join() is a no-op on it.

    The decoded body, in proxy mode, fails fast if the alias is missing, writes
    the proxy mimocode.json to both ``{home}/.config/mimocode/mimocode.json``
    (canonical) and ``./mimocode.json``, optionally (when ``BF_PR8_DEBUG`` is
    set) dumps a redacted BF_DIAG banner to STDOUT (synced via agent/mimo.txt),
    neutralises the OPENAI_* env collision, then ``exec``s mimo so it replaces
    the shell.
    """
    import base64

    node = f"{_BENCHFLOW_NODE_PREFIX}/bin/node"
    # NOTE: this body is a here-doc-free shell program; $A/$B/$K expand at launch
    # in the sandbox (the proxy alias + proxy URL + proxy key benchflow injects).
    body = r"""
A="${BENCHFLOW_LITELLM_MODEL_ALIAS:-}"
B="${OPENAI_BASE_URL:-}"
K="${OPENAI_API_KEY:-}"
# HARD ERROR (fail fast): proxy URL is present but the alias is empty. Without
# the alias the custom "openai" provider has no models map, so mimo would raise
# ProviderModelNotFoundError and end the turn with ZERO captured LLM requests —
# a silent reward-0 that looks like a model failure. Surface it loudly instead.
if [ -n "$B" ] && [ -z "$A" ]; then
  echo "mimo-acp launcher FATAL: OPENAI_BASE_URL is set (proxy mode) but BENCHFLOW_LITELLM_MODEL_ALIAS is empty; the custom openai provider would have no model and mimo would emit zero LLM requests (ProviderModelNotFound). Aborting." 1>&2
  exit 78
fi
if [ -n "$B" ] && [ -n "$A" ]; then
  # Canonical config location MiMo Code (OpenCode fork) reads:
  # {home}/.config/mimocode/mimocode.json (matches benchflow-core's native mimo
  # agent). Also written to ./mimocode.json (cwd) as a belt-and-suspenders for
  # the proven-working run, so the routing is not cwd-dependent.
  CFG_HOME="${HOME:-/root}/.config/mimocode"
  mkdir -p "$CFG_HOME"
  CFG_JSON='{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openai": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "BenchFlow Proxy",
      "options": { "baseURL": "'"$B"'", "apiKey": "'"${K:-benchflow}"'" },
      "models": { "'"$A"'": { "name": "'"$A"'" } }
    }
  },
  "model": "openai/'"$A"'"
}'
  printf '%s\n' "$CFG_JSON" > "$CFG_HOME/mimocode.json"
  printf '%s\n' "$CFG_JSON" > ./mimocode.json
  CFG_WRITTEN=yes
else
  CFG_WRITTEN=no
fi
if [ -n "${BF_PR8_DEBUG:-}" ]; then
  H=$(printf %s "$B" | sed -E "s#^[a-z]+://([^@]*@)?([^/:?]+).*#\2#")
  echo "BF_DIAG base_url_set=$([ -n \"$B\" ] && echo yes || echo no) host=${H:-NONE}"
  echo "BF_DIAG api_key_set=$([ -n \"$K\" ] && echo yes || echo no)"
  echo "BF_DIAG alias=${A:-NONE}"
  echo "BF_DIAG cfg_written=$CFG_WRITTEN cfg_cwd=$(pwd)/mimocode.json cfg_home=${HOME}/.config/mimocode/mimocode.json MIMOCODE_CONFIG=${MIMOCODE_CONFIG:-unset}"
  echo BF_DIAG mimocode_begin
  for p in ./mimocode.json "${HOME}/.config/mimocode/mimocode.json" "${MIMOCODE_CONFIG:-}"; do
    if [ -n "$p" ] && [ -f "$p" ]; then
      sed -E -e 's#("apiKey"[[:space:]]*:[[:space:]]*")[^"]*#\1<REDACTED>#g' \
             -e 's#://[^@/"]*@#://<REDACTED>@#g' "$p" \
        | awk -v pfx="BF_DIAG_CFG $p: " '{print pfx $0}'
    fi
  done
  echo BF_DIAG mimocode_end
fi
unset OPENAI_BASE_URL OPENAI_API_KEY
"""
    body = body + f"exec {node} {_MIMO_BIN} acp\n"
    b64 = base64.b64encode(body.encode()).decode()
    script = "/tmp/mimo-acp-launch.sh"
    # printf|base64 pipeline: no internal whitespace in the b64 payload, so the
    # which-rewrite's split()/" ".join() round-trip is a no-op and the shell
    # metacharacters (| > &&) survive intact.
    return f"printf '%s' '{b64}' | base64 -d > {script} && sh {script}"


def register() -> None:
    """Register the ``mimo`` agent (and its aliases) into BenchFlow."""
    register_agent(
        name="mimo",
        install_cmd=_install_cmd(),
        launch_cmd=_launch_cmd(),
        protocol="acp",
        # Usage-capture for any gateway-routed model lands in
        # OPENAI_BASE_URL/OPENAI_API_KEY.
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        # provider/model so benchflow's set_config_option(value) is
        # "openai/<alias>" — the prefix our launcher's mimocode.json provider key
        # ("openai") matches. The bare alias alone yields ProviderModelNotFound.
        acp_model_format="provider/model",
        supports_acp_set_model=True,
        requires_env=[],
        install_timeout=1200,  # node bootstrap + npm install is heavy
        description=(
            "MiMo Code (Xiaomi, OpenCode fork) native `mimo acp` ACP server "
            "via the `mimo` CLI — no server.mjs (mimo is the ACP server)"
        ),
    )
    for alias in _ALIASES:
        AGENT_ALIASES.setdefault(alias, "mimo")

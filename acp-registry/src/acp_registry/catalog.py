"""Catalog of the Agent Client Protocol registry, classified for BenchFlow.

Every agent in the public ACP registry (https://agentclientprotocol.com/get-started/registry,
snapshot in ``registry.snapshot.json``) is ACP-native: it speaks ACP over stdio
already. So "adapting" one to BenchFlow is not writing a server — it is a thin
registration: install the agent, launch it in ACP mode, and route its model
calls through BenchFlow's gateway so the benchmark's model is enforced and usage
is captured.

Whether that routing is *possible* is the whole question, and it splits the
registry cleanly:

``native``        BenchFlow already ships a built-in for this agent. Use it
                  (``--agent <native_name>``); we do not shadow it here.
``wired``         Registered by this package with a provider profile that routes
                  correctly **by construction** (confirmed env vars + a model
                  format BenchFlow can emit). ``register()`` installs it.
``runnable``      Installs + launches its ACP server headlessly in a benchflow
                  task env, but its model is NOT enforced through BenchFlow's
                  gateway (it runs on its own/vendor backend, or needs a vendor
                  key at eval time). Executable, but not a faithful
                  model-controlled eval. ``register()`` does NOT install these.
``catalog``       BYO-provider: the agent *can* be pointed at an arbitrary
                  OpenAI/Anthropic-compatible base URL, so it is adaptable — but
                  it is not wired yet because it needs something this first pass
                  doesn't ship (a config-file writer, a binary installer, a uvx
                  bootstrap, or a model-id format BenchFlow can't emit). Each
                  entry carries the exact recipe in ``reason``/``wiring`` so
                  wiring it is a one-spec change, not a research project.
``vendor-locked`` Authenticates only to its vendor's backend — no arbitrary base
                  URL. BenchFlow cannot enforce the benchmark's model or capture
                  usage through the gateway, so it can't be a *faithful* eval.
``out-of-scope``  Not an LLM coding/eval agent (e.g. an agent marketplace).

The honesty bar (see the repo README): a ``wired`` entry means "registers and
routes correctly by construction," NOT "passes real workloads." Only
``verified`` entries have been run end-to-end on a real task, and only on the
exact tasks named. ``catalog`` recipes are derived from upstream docs/source,
not from a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- status taxonomy -------------------------------------------------------
NATIVE = "native"
WIRED = "wired"
# RUNNABLE — installs + launches its ACP server headlessly in a benchflow task
# env, but its model is NOT enforced through BenchFlow's gateway (it runs on its
# own/vendor backend, or needs a vendor key at eval time). Executable, but not a
# faithful model-controlled eval. (No extra invariant beyond a valid
# distribution: RUNNABLE may be uvx and may have no env_mapping.)
RUNNABLE = "runnable"
CATALOG = "catalog"
VENDOR_LOCKED = "vendor-locked"
OUT_OF_SCOPE = "out-of-scope"

_STATUSES = frozenset({NATIVE, WIRED, RUNNABLE, CATALOG, VENDOR_LOCKED, OUT_OF_SCOPE})

# Distribution kinds, mirroring the registry's ``distribution`` key.
NPX = "npx"
UVX = "uvx"
BINARY = "binary"


@dataclass(frozen=True)
class AcpAgent:
    """One ACP-registry agent, classified for BenchFlow.

    ``registry_id``/``name``/``license``/``repository``/``distribution``/
    ``package``/``acp_args`` mirror the registry entry. The rest is BenchFlow's
    view: how (and whether) the agent routes through the gateway.
    """

    registry_id: str
    name: str
    license: str
    repository: str
    distribution: str  # NPX | UVX | BINARY
    package: str  # npm/pypi spec; "" for binary
    acp_args: str  # launch args that put the agent in ACP-over-stdio mode
    status: str
    summary: str

    # --- routing profile (set for WIRED; recorded for CATALOG) ------------
    api_protocol: str = ""  # "openai-completions" | "anthropic-messages" | ...
    env_mapping: dict[str, str] = field(default_factory=dict)
    launch_env: dict[str, str] = field(default_factory=dict)  # constant env
    acp_model_format: str = "bare"
    supports_acp_set_model: bool = False
    model_via: str = ""  # "env" | "flag" | "config-file" | "set_model" | "config-option"
    bin_name: str = ""  # npm bin name (npx install/launch); "" if N/A
    npm_extra: tuple[str, ...] = ()  # extra npm pkgs to install beside an npx agent
    #   (e.g. a provider SDK the agent imports lazily — deepagents needs @langchain/openai)

    # --- pointers / rationale ---------------------------------------------
    native_name: str = ""  # the BenchFlow built-in (status == NATIVE)
    verified: tuple[str, ...] = ()  # tasks this agent was actually run on
    known_issue: str = ""  # a real runtime caveat surfaced by an end-to-end run
    reason: str = ""  # why catalog/locked/out-of-scope, or notes for wired
    source: str = ""  # doc/source URL backing the routing claim

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"{self.registry_id}: bad status {self.status!r}")
        if self.distribution not in {NPX, UVX, BINARY}:
            raise ValueError(
                f"{self.registry_id}: bad distribution {self.distribution!r}"
            )
        if self.status == NATIVE and not self.native_name:
            raise ValueError(f"{self.registry_id}: native entry needs native_name")
        if self.status == WIRED:
            if self.distribution not in {NPX, BINARY}:
                # npx (reuses BenchFlow's _js_agent_install) and binary (per-arch
                # download from the registry snapshot) are wired today; uvx is not.
                raise ValueError(
                    f"{self.registry_id}: wired entries must be npx or binary"
                )
            if not self.env_mapping:
                raise ValueError(f"{self.registry_id}: wired entry needs env_mapping")
            if self.distribution == NPX and not self.bin_name:
                raise ValueError(f"{self.registry_id}: npx wired needs bin_name")
        # RUNNABLE carries no extra invariant: the npx-or-binary / env_mapping
        # contract is WIRED-only. A RUNNABLE entry may be uvx and may have no
        # env_mapping (e.g. a local-model agent); a valid distribution (checked
        # above) is all that is required.


# ---------------------------------------------------------------------------
# The catalog. One entry per ACP-registry agent (registry v1.0.0 snapshot).
# Routing facts (env vars, BYO-vs-locked) were researched from each agent's
# own docs/source on 2026-06-13; ``source`` cites the backing reference.
# ---------------------------------------------------------------------------
ACP_AGENTS: tuple[AcpAgent, ...] = (
    # === native: BenchFlow already ships these ============================
    AcpAgent(
        registry_id="claude-acp",
        name="Claude Agent",
        license="proprietary",
        repository="https://github.com/agentclientprotocol/claude-agent-acp",
        distribution=NPX,
        package="@agentclientprotocol/claude-agent-acp",
        acp_args="",
        status=NATIVE,
        native_name="claude-agent-acp",
        summary="Anthropic Claude Code over ACP.",
        reason="Shipped as BenchFlow's built-in `claude-agent-acp` "
        "(subscription auth + ANTHROPIC_* env_mapping). Use that.",
    ),
    AcpAgent(
        registry_id="codex-acp",
        name="Codex CLI",
        license="Apache-2.0",
        repository="https://github.com/zed-industries/codex-acp",
        distribution=BINARY,
        package="",
        acp_args="",
        status=NATIVE,
        native_name="codex-acp",
        summary="OpenAI Codex CLI over ACP.",
        reason="Shipped as BenchFlow's built-in `codex-acp` "
        "(@agentclientprotocol/codex-acp, openai-responses). Use that.",
    ),
    AcpAgent(
        registry_id="gemini",
        name="Gemini CLI",
        license="Apache-2.0",
        repository="https://github.com/google-gemini/gemini-cli",
        distribution=NPX,
        package="@google/gemini-cli",
        acp_args="--acp",
        status=NATIVE,
        native_name="gemini",
        summary="Google Gemini CLI over ACP.",
        reason="Shipped as BenchFlow's built-in `gemini` "
        "(GEMINI_API_KEY + subscription auth). Use that.",
    ),
    AcpAgent(
        registry_id="opencode",
        name="OpenCode",
        license="MIT",
        repository="https://github.com/anomalyco/opencode",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=NATIVE,
        native_name="opencode",
        summary="OpenCode coding agent over ACP.",
        reason="Shipped as BenchFlow's built-in `opencode` "
        "(provider/model format). Use that.",
    ),
    AcpAgent(
        registry_id="pi-acp",
        name="pi ACP",
        license="MIT",
        repository="https://github.com/svkozak/pi-acp",
        distribution=NPX,
        package="pi-acp",
        acp_args="",
        status=NATIVE,
        native_name="pi-acp",
        summary="Pi coding agent over ACP.",
        reason="Shipped as BenchFlow's built-in `pi-acp` "
        "(registered-provider/model). Also adapted via AI SDK in `ai-sdk/harness-pi`.",
    ),
    # === wired: registered + routes correctly by construction =============
    AcpAgent(
        registry_id="qwen-code",
        name="Qwen Code",
        license="Apache-2.0",
        repository="https://github.com/QwenLM/qwen-code",
        distribution=NPX,
        package="@qwen-code/qwen-code@0.18.0",
        acp_args="--acp",
        status=WIRED,
        summary="Alibaba's Qwen Code (a Gemini-CLI fork) over ACP — "
        "reads any OpenAI-compatible provider straight from env.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "OPENAI_MODEL",
        },
        acp_model_format="bare",
        supports_acp_set_model=False,  # model is fixed at launch via OPENAI_MODEL
        model_via="env",
        bin_name="qwen",
        verified=(
            "hello-world (reward 1.0)",
            "skillsbench/citation-check (reward 1.0, 33 tool calls)",
        ),
        known_issue="qwen-code advertises an ACP `model` session config option "
        "whose values it validates against its OWN model list, so BenchFlow's "
        "capability-first dispatch fails when it tries to set the benchmark's "
        "model id over ACP (-32603) — seen with both a gateway alias and a bare "
        "`deepseek-v4-flash`. The model is already delivered via env "
        "(OPENAI_MODEL), so the fix is to NOT drive it over ACP: this package "
        "enables BenchFlow's `acp_model_via_env` flag when present. That flag is "
        "a proposed BenchFlow change (see the PR); on a build without it, "
        "`register()` warns and qwen-code fails at model configuration.",
        reason="Cleanest fit in the registry: base URL, key, AND model are all "
        "plain env vars (OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL), so "
        "BenchFlow's env_mapping routes it with no config file and no model-id "
        "translation. Verified end-to-end on DeepSeek via Daytona (reward 1.0 on "
        "hello-world) with the `acp_model_via_env` fix.",
        source="https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/",
    ),
    # === catalog: BYO-redirectable, recipe given, not yet wired ===========
    AcpAgent(
        registry_id="goose",
        name="goose",
        license="Apache-2.0",
        repository="https://github.com/block/goose",
        distribution=BINARY,
        package="",
        acp_args="acp",
        bin_name="goose",
        status=WIRED,
        summary="Block's general agent; broad provider support incl. any "
        "OpenAI-compatible host. Verified running in BenchFlow.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "GOOSE_MODEL",
        },
        launch_env={
            "GOOSE_PROVIDER": "openai",
            # goose's openai provider takes a host + base path (not one URL); the
            # gateway/provider base URL is the host, the OpenAI path is constant.
            "OPENAI_HOST": "$BENCHFLOW_PROVIDER_BASE_URL",
            "OPENAI_BASE_PATH": "v1/chat/completions",
        },
        model_via="env",
        verified=(
            "hello-world (reward 1.0)",
            "skillsbench/citation-check (ran end-to-end, no error; reward 0.0 "
            "— agent didn't solve it with deepseek-v4-flash, not an integration "
            "failure)",
        ),
        known_issue="OPENAI_HOST is set to the provider base URL and OPENAI_BASE_PATH "
        "to a constant v1/chat/completions — correct for a host-only base URL "
        "(DeepSeek, the LiteLLM gateway). A provider whose base URL already carries "
        "a path would double it up; such providers need the custom_providers JSON "
        "instead.",
        reason="Per-arch Linux binary (x86_64 + aarch64) downloaded from the "
        "registry snapshot; all-env wiring (GOOSE_PROVIDER=openai, OPENAI_HOST/"
        "OPENAI_BASE_PATH, OPENAI_API_KEY, GOOSE_MODEL) — no config file. Verified "
        "end-to-end on DeepSeek via Daytona.",
        source="https://block.github.io/goose/docs/getting-started/providers",
    ),
    AcpAgent(
        registry_id="stakpak",
        name="Stakpak",
        license="Apache-2.0",
        repository="https://github.com/stakpak/agent",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=WIRED,
        summary="DevOps agent; BYO-LLM custom OpenAI-compatible endpoint, per-arch "
        "Linux binary (`stakpak acp`).",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "OPENAI_MODEL",
        },
        acp_model_format="provider/model",
        supports_acp_set_model=False,
        model_via="config-file",
        bin_name="stakpak",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 2 upstream "
            "/v1/chat/completions, initialize+session/new OK — wired by "
            "construction, no real-task reward claimed",
        ),
        known_issue="The ACP model->provider resolver is a substring heuristic "
        "that only knows anthropic/openai/google (else falls through to the "
        "hosted `stakpak` provider), and the ACP set_model path validates against "
        "the static models.dev catalog — so the model is delivered out-of-band via "
        "config, NOT over ACP (supports_acp_set_model=False).",
        reason="Per-arch Linux binary (v0.3.88). UNBLOCKED: the launcher generates "
        "a valid config via `stakpak auth login --provider openai --api-key K "
        "--endpoint BASE` (writes ~/.stakpak/config.toml providers.openai."
        "{api_endpoint,auth.key}), then forces the default-profile model to "
        "`openai/<model>` so the substring resolver picks the openai provider + our "
        "endpoint; state is isolated under HOME=$STAKPAK_BF_HOME and re-written from "
        "env each launch. Verified wired-by-construction on the routing smoke "
        "(wire model `openai/deepseek-v4-flash`).",
        source="https://github.com/stakpak/agent",
    ),
    AcpAgent(
        registry_id="vtcode",
        name="VT Code",
        license="MIT",
        repository="https://github.com/vinhnx/VTCode",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=WIRED,
        summary="Rust coding agent; [[custom_providers]] with arbitrary base_url.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        model_via="config-file",
        bin_name="vtcode",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 1 upstream "
            "/v1/chat/completions, stopReason end_turn — wired by construction, "
            "no real-task reward claimed",
        ),
        known_issue="A prior DeepSeek/Daytona probe saw vtcode close stdout "
        "(`pipe_closed`) after the session opened; the routing call still fires "
        "(smoke N=1), but full real-task stability is unverified.",
        reason="Per-arch Linux binary; routes any OpenAI-compatible host via a "
        "launch-written vtcode.toml [[custom_providers]] (base_url + "
        "api_key_env=OPENAI_API_KEY) + [agent] default_model, with the ACP bridge "
        "enabled by VT_ACP_ENABLED=1 — that config-file writer is what unblocked "
        "it. base_url must include the /v1 suffix (vtcode posts "
        "{base_url}/chat/completions, no auto-append).",
        source="https://github.com/vinhnx/vtcode",
    ),
    AcpAgent(
        registry_id="crow-cli",
        name="crow-cli",
        license="Apache-2.0",
        repository="https://github.com/crow-cli/crow-cli",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=WIRED,
        summary="Vendor-agnostic agent; any OpenAI-compatible endpoint.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "OPENAI_MODEL",
        },
        model_via="env",
        bin_name="crow-cli",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 2 upstream "
            "/v1/chat/completions, stopReason end_turn — wired by construction, "
            "no real-task reward claimed",
        ),
        reason="Per-arch Linux binary (`crow-cli acp`); routes any "
        "OpenAI-compatible host via a launch-written ~/.crow config.yaml "
        "(providers/base_url/api_key/model with ${ENV} interpolation) — the binary "
        "installer + config-file writer (which also ships the required crow-mcp "
        "tool server and a full sqlite:/// db_uri) is what unblocked it.",
        source="https://github.com/crow-cli/crow-cli",
    ),
    AcpAgent(
        registry_id="kimi",
        name="Kimi CLI",
        license="Apache-2.0",
        repository="https://github.com/MoonshotAI/kimi-cli",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=CATALOG,
        summary="Moonshot's Kimi CLI; openai_legacy provider type takes any "
        "OpenAI chat-completions host.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BLOCKED headless (smoke-confirmed): `kimi acp` mandates "
        "interactive Kimi-account OAuth — session/new returns -32000 "
        "'Authentication required' (authMethod login/terminal runs `kimi login`) "
        "even with a complete openai_legacy provider config; `kimi login` is "
        "OAuth-only with no api-key/token env bypass.",
        source="https://github.com/MoonshotAI/kimi-cli",
    ),
    AcpAgent(
        registry_id="mistral-vibe",
        name="Mistral Vibe",
        license="Apache-2.0",
        repository="https://github.com/mistralai/mistral-vibe",
        distribution=BINARY,
        package="",
        acp_args="",
        status=WIRED,
        summary="Mistral's agent; custom provider presets with api_style=openai "
        "+ arbitrary api_base. ACP via the vibe-acp binary.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "OPENAI_MODEL",
        },
        model_via="env",
        bin_name="vibe-acp",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 2 upstream "
            "/v1/chat/completions, stopReason end_turn — wired by construction, "
            "no real-task reward claimed",
        ),
        reason="Dedicated `vibe-acp` per-arch Linux binary; routes any "
        "OpenAI-compatible host via a launch-written ~/.vibe/config.toml "
        "[[providers]] (api_base + api_key_env_var=OPENAI_API_KEY, "
        "api_style=openai) + [[models]] active_model — the binary installer + "
        "config writer is what unblocked it.",
        source="https://github.com/mistralai/mistral-vibe",
    ),
    AcpAgent(
        registry_id="kilo",
        name="Kilo",
        license="MIT",
        repository="https://github.com/Kilo-Org/kilocode",
        distribution=NPX,
        package="@kilocode/cli",
        acp_args="acp --log-level ERROR --print-logs",
        status=WIRED,
        summary="Kilo Code CLI (OpenCode-based); a kilo.jsonc declares an "
        "@ai-sdk/openai-compatible provider.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "OPENAI_MODEL",
        },
        model_via="env",
        bin_name="kilo",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 2 upstream "
            "/v1/chat/completions, stopReason end_turn — wired by construction, "
            "no real-task reward claimed",
        ),
        known_issue="kilo.json's baseURL is written verbatim, so the gateway base "
        "URL must already carry any required path suffix (e.g. .../v1); a host-only "
        "base needs the suffix appended.",
        reason="npx (@kilocode/cli); routes any OpenAI-compatible provider via a "
        "launch-time kilo.json writer that declares a `deepseek` "
        "@ai-sdk/openai-compatible provider (baseURL + {env:OPENAI_API_KEY}) and "
        "templates the benchmark model from $OPENAI_MODEL into the config (the "
        "model is a config KEY, so it can't ride kilo's {env:} value substitution) "
        "— that config-file writer is what unblocked it.",
        source="https://kilo.ai/docs/code-with-ai/platforms/cli",
    ),
    AcpAgent(
        registry_id="dirac",
        name="Dirac",
        license="Apache-2.0",
        repository="https://github.com/dirac-run/dirac",
        distribution=NPX,
        package="dirac-cli",
        acp_args="--acp",
        status=WIRED,
        summary="BYO agent: 'use any OpenAI-compatible provider by providing the "
        "base URL and model ID.'",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_API_BASE",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "OPENAI_MODEL",
        },
        model_via="env",
        bin_name="dirac",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 6 upstream "
            "/v1/chat/completions, stopReason end_turn — wired by construction, "
            "no real-task reward claimed",
        ),
        known_issue="dirac can close its stdout mid-run (benchflow `pipe_closed`); "
        "if it routes >=1 request first it still counts as routed, and the smoke "
        "saw a clean end_turn (6 requests), but full real-task stability is "
        "unverified.",
        reason="npx, pure-JS (reads OPENAI_API_BASE, not OPENAI_BASE_URL); ACP "
        "mode ignores the --model/--provider flags, so the launch seeds persisted "
        "config non-interactively via `dirac auth --provider openai --modelid "
        "$OPENAI_MODEL --baseurl $OPENAI_API_BASE --config <dir>`, forcing the "
        "openai-compatible provider through the gateway — that config seeder is "
        "what unblocked it.",
        source="https://github.com/dirac-run/dirac",
    ),
    AcpAgent(
        registry_id="deepagents",
        name="DeepAgents",
        license="MIT",
        repository="https://github.com/langchain-ai/deepagentsjs",
        distribution=NPX,
        package="deepagents-acp@0.1.12",
        acp_args="",
        status=NATIVE,
        native_name="deepagents",
        summary="LangChain 'deep agents' over ACP.",
        reason="Now shipped as BenchFlow's built-in `deepagents` (LangChain "
        "create_deep_agent via an ACP shim) AND as a first-class manifest in "
        "acp/deepagents/ in this repo — use that. This package's first pass wired "
        "the upstream deepagents-acp npm distribution (env_mapping + a "
        "`--model openai:<model>` flag, @langchain/openai installed alongside; "
        "verified reward 1.0 on hello-world via Daytona) before core shipped the "
        "shim; that recipe is preserved in git history.",
        source="https://docs.langchain.com/oss/javascript/deepagents/acp",
    ),
    AcpAgent(
        registry_id="fast-agent",
        name="fast-agent",
        license="Apache-2.0",
        repository="https://github.com/evalstate/fast-agent",
        distribution=UVX,
        package="fast-agent-acp==0.7.18",
        acp_args="-x",
        status=RUNNABLE,
        summary="MCP-centric general agent framework; per-provider base_url "
        "overrides. A good 'not just coding' agent.",
        api_protocol="openai-completions",
        env_mapping={
            # fast-agent does NOT read a plain OPENAI_BASE_URL; base_url is the
            # pydantic-settings nested form OPENAI__BASE_URL (or fastagent.config.yaml).
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI__BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI__API_KEY",
        },
        model_via="flag",
        reason="RUNNABLE: installs + launches headless via uvx (smoke: 1 upstream "
        "/v1/chat/completions, model=deepseek-v4-flash, initialize+session/new "
        "OK) — gateway-routable but uvx, outside the wired npx-or-binary policy, "
        "so no wired claim. Coords: PyPI fast-agent-acp==0.7.18 (console script "
        "from its dep fast-agent-mcp==0.7.18); reads pydantic nested env "
        "OPENAI__BASE_URL / OPENAI__API_KEY (NOT plain OPENAI_BASE_URL) + --model "
        "openai.<id>; needs a uv-managed CPython 3.13 bootstrap.",
        source="https://fast-agent.ai/ref/config_file/",
    ),
    AcpAgent(
        registry_id="autohand",
        name="Autohand Code",
        license="Apache-2.0",
        repository="https://github.com/autohandai/autohand-acp",
        distribution=NPX,
        package="@autohandai/autohand-acp",
        acp_args="",
        status=RUNNABLE,
        summary="BYO agent; works with OpenRouter, OpenAI, Bedrock, DeepSeek, "
        "Z.ai, local models. Optional account is telemetry-only.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="RUNNABLE: installs + launches headless, ACP handshake OK (smoke: "
        "initialize+session/new OK), but not gateway-enforced — despite the BYO "
        "marketing (OpenRouter/OpenAI/Bedrock/DeepSeek/Z.ai/local), the ACP "
        "adapter's config path can't be driven non-interactively to an arbitrary "
        "endpoint+key+model, so model routing isn't gateway-controlled. Revisit if "
        "upstream adds a headless config.",
        source="https://github.com/autohandai/code-cli",
    ),
    AcpAgent(
        registry_id="nova",
        name="Nova",
        license="MIT",
        repository="https://github.com/Compass-Agentic-Platform/nova",
        distribution=NPX,
        package="@compass-ai/nova",
        acp_args="acp",
        status=RUNNABLE,
        summary="Agent built on @anthropic-ai/sdk; over ACP it serves only "
        "built-in Claude models (anthropic-messages), retargetable solely via "
        "COMPASS_ANTHROPIC_BASE_URL.",
        api_protocol="anthropic-messages",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "COMPASS_ANTHROPIC_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "ANTHROPIC_API_KEY",
        },
        bin_name="nova",
        model_via="env",
        reason="RUNNABLE: installs + launches headless (smoke: initialize+session/"
        "new OK) but routes to its own Claude-only backend — nova's ACP runtime is "
        "anthropic-messages ONLY and exposes only built-in Claude models, "
        "retargetable solely via COMPASS_ANTHROPIC_BASE_URL (the standard "
        "ANTHROPIC_BASE_URL is ignored; DEFAULT_OPENAI_BASE_URL is an internal "
        "constant, not env-overridable), so it cannot serve BenchFlow's "
        "openai-completions gateway / deepseek-v4-flash (smoke logged "
        "upstreamRequests=0 for the ACP turn). Usable only if the gateway exposes "
        "an anthropic-messages endpoint AND the run uses a Claude-family model id "
        "via COMPASS_ANTHROPIC_BASE_URL.",
        source="https://github.com/Compass-Agentic-Platform/nova",
    ),
    AcpAgent(
        registry_id="cline",
        name="Cline",
        license="Apache-2.0",
        repository="https://github.com/cline/cline",
        distribution=NPX,
        package="cline",
        acp_args="--acp",
        status=RUNNABLE,
        summary="Popular coding agent; OpenAI-compatible routing exists but is "
        "currently fragile.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="RUNNABLE: installs + launches headless (smoke: initialize+session/"
        "new OK) but model routing is not gateway-enforced — `cline auth "
        "--provider openai-native --baseurl ... --modelid ...` exists, yet "
        "multiple open issues report the custom base URL being ignored (calls "
        "still hit api.openai.com), so faithful gateway routing is not claimed. "
        "Promote to WIRED only after verifying requests actually reach the gateway.",
        source="https://github.com/cline/cline/blob/main/apps/cli/README.md",
    ),
    AcpAgent(
        registry_id="github-copilot-cli",
        name="GitHub Copilot",
        license="proprietary",
        repository="https://github.com/github/copilot-cli",
        distribution=NPX,
        package="@github/copilot@1.0.65",
        acp_args="--acp",
        status=WIRED,
        summary="GitHub Copilot CLI; BYOK (own provider keys) is GA — NOT "
        "backend-locked. Built-in `--acp` server.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "COPILOT_PROVIDER_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "COPILOT_PROVIDER_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "COPILOT_MODEL",
        },
        acp_model_format="bare",
        bin_name="copilot",
        model_via="env",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 2 upstream "
            "/v1/chat/completions, initialize+session/new OK — wired by "
            "construction, no real-task reward claimed",
        ),
        reason="npx (@github/copilot@1.0.65) via its built-in `--acp` server. "
        "UNBLOCKED on 1.0.65 (resolves the prior 1.0.61 'Authentication required' "
        "block): routes any OpenAI-compatible provider through the first-class "
        "BYOK path purely via env (COPILOT_PROVIDER_TYPE=openai + "
        "COPILOT_PROVIDER_BASE_URL/_API_KEY + COPILOT_MODEL, bare wire model). "
        "Setting COPILOT_PROVIDER_BASE_URL makes the CLI use that provider instead "
        "of GitHub's routing and, per `copilot help environment`, 'GitHub "
        "authentication is not required' — so ACP launches fully headless with NO "
        "GitHub token. (The npx launch path can't carry launch_env, so the "
        "constant COPILOT_PROVIDER_TYPE=openai is exported by the agent launcher.)",
        source="https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-byok-models",
    ),
    AcpAgent(
        registry_id="codebuddy-code",
        name="Codebuddy Code",
        license="proprietary",
        repository="https://www.codebuddy.ai",
        distribution=NPX,
        package="@tencent-ai/codebuddy-code@2.106.3",
        acp_args="--acp",
        status=WIRED,
        summary="Tencent's coding agent (a Claude-Code fork); models.json supports "
        "fully custom OpenAI-format models (the BYO escape hatch). `--acp`.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "OPENAI_MODEL",
        },
        acp_model_format="bare",
        model_via="config-file",
        bin_name="codebuddy",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 4 upstream "
            "/v1/chat/completions, initialize+session/new OK — wired by "
            "construction, no real-task reward claimed",
        ),
        known_issue="In the smoke, stopReason is null/promptTimeout because the "
        "mock's canned reply does not satisfy CodeBuddy's internal topic-analyzer "
        "turn loop (it keeps re-requesting); the ACP handshake + routing (4 "
        "upstream calls, bare deepseek-v4-flash) are the anchor and passed.",
        reason="npx (@tencent-ai/codebuddy-code). UNBLOCKED: `--acp` routes the CLI "
        "into its headless bundle; the launcher writes a models.json custom model "
        "(id tagged 'custom' → POSTs <url>/chat/completions with a BARE wire model; "
        "url/apiKey go through CodeBuddy's own ${ENV} interpolation, default model "
        "via CODEBUDDY_MODEL). Login bypass: a custom model + a dummy "
        "CODEBUDDY_API_KEY skips the Tencent OAuth gate, so initialize+session/new "
        "succeed headlessly. CODEBUDDY_CONFIG_DIR isolates state. chat-completions "
        "only; model is config-owned (supports_acp_set_model=False).",
        source="https://www.codebuddy.ai/docs/cli/acp",
    ),
    AcpAgent(
        registry_id="dimcode",
        name="DimCode",
        license="proprietary",
        repository="https://dim.qwenkimi.com",
        distribution=NPX,
        package="dimcode@0.2.2",
        acp_args="acp",
        status=WIRED,
        summary="BYO agent ('OpenAI, Anthropic, or custom endpoint'; bring your "
        "own model). npm wrapper that fetches a per-arch native binary; `dim acp`.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "OPENAI_MODEL",
        },
        model_via="config-file",
        bin_name="dim",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 2 upstream "
            "/v1/chat/completions, initialize+session/new OK — wired by "
            "construction, no real-task reward claimed",
        ),
        reason="npx (dimcode@0.2.2; the npm wrapper fetches a ~140MB per-arch "
        "native binary). UNBLOCKED contrary to the old '/connect only' note: a "
        "headless `dim provider add deepseek --api-key --base-url --model` CLI "
        "persists the connection to ~/.dimcode/v2/dimcode.sqlite, so the launcher "
        "runs it (reading OPENAI_BASE_URL/_API_KEY/_MODEL) before `dim acp`. The "
        "`deepseek` provider uses the native openai-compatible driver (POSTs "
        "base_url + /chat/completions, sends the model id BARE, accepts any "
        "--model), so calls route through the gateway; the model is config-owned.",
        source="https://dim.qwenkimi.com/docs/acp",
    ),
    AcpAgent(
        registry_id="grok-build",
        name="Grok Build",
        license="proprietary",
        repository="https://x.ai/cli",
        distribution=BINARY,
        package="",
        acp_args="agent stdio",
        status=WIRED,
        summary="xAI's Grok CLI; surprisingly BYO — GROK_MODELS_BASE_URL routes "
        "all chat traffic through an arbitrary OpenAI-completions gateway. "
        "Per-arch Linux static-pie binary (`grok agent stdio`).",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "GROK_MODELS_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "XAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "GROK_DEFAULT_MODEL",
        },
        model_via="env",
        bin_name="grok",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 3 upstream "
            "/v1/chat/completions, initialize+session/new OK — wired by "
            "construction, no real-task reward claimed",
        ),
        known_issue="The wire model id is a FIXED literal 'grok-build' (the "
        "agent's built-in coding model) regardless of GROK_DEFAULT_MODEL or ACP "
        "set_model, so the benchmark model must be served/aliased as 'grok-build' "
        "on the gateway (e.g. a LiteLLM alias). Access-gated for xAI's own backend "
        "(SuperGrok/Premium+), but headless launch + handshake + gateway routing "
        "need no account.",
        reason="Per-arch Linux binary (v0.2.20). UNBLOCKED: GROK_MODELS_BASE_URL "
        "routes all chat traffic through an arbitrary OpenAI-completions gateway "
        "with no xAI OAuth — the launcher points it at the gateway, supplies "
        "XAI_API_KEY, sets GROK_OAUTH_ENABLED=0, disables autoupdate/telemetry, and "
        "isolates GROK_HOME under $HOME.",
        source="https://docs.x.ai/build",
    ),
    AcpAgent(
        registry_id="junie",
        name="Junie",
        license="proprietary",
        repository="https://github.com/JetBrains/junie",
        distribution=BINARY,
        package="",
        acp_args="--acp true",
        status=RUNNABLE,
        summary="JetBrains Junie CLI; 'the LLM-agnostic coding agent' — "
        "custom-model JSON profiles with arbitrary baseUrl.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="RUNNABLE: installs + launches headless via the JetBrains "
        "shell-installer binary (`--acp true`), ACP handshake OK (smoke: "
        "initialize+session/new OK), but its BYO custom-model JSON "
        "($JUNIE_HOME/models/*.json id/baseUrl/apiType/apiKey + --model "
        "custom:<id>) is not wired here, so model routing is not gateway-enforced. "
        "Proprietary (JetBrains AI Service ToS).",
        source="https://junie.jetbrains.com/docs",
    ),
    AcpAgent(
        registry_id="poolside",
        name="Poolside",
        license="proprietary",
        repository="https://github.com/poolsideai/pool",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=RUNNABLE,
        summary="Poolside 'pool' CLI; connects to any OpenAI-compatible chat "
        "completions API (incl. LiteLLM, OpenRouter, Ollama).",
        api_protocol="openai-completions",
        model_via="flag",
        reason="RUNNABLE: installs + launches headless (smoke: initialize+session/"
        "new OK) but the ACP server path can't be driven headless to a custom "
        "endpoint — `pool exec --api-url` takes an arbitrary OpenAI-compatible "
        "URL, yet the ACP path advertises a validated model option and routes "
        "through Poolside, so model routing is not gateway-enforced. Proprietary "
        "shell-installer binary.",
        source="https://docs.poolside.ai",
    ),
    AcpAgent(
        registry_id="minion-code",
        name="Minion Code",
        license="AGPL-3.0",
        repository="https://github.com/femto/minion-code",
        distribution=UVX,
        package="minion-code@0.1.44",
        acp_args="acp",
        status=RUNNABLE,
        summary="Python coding agent over ACP (uvx-distributed).",
        model_via="config-file",
        reason="RUNNABLE: installs + launches headless via uvx (smoke: 2 upstream "
        "/v1/chat/completions, initialize+session/new OK) — gateway-routable but "
        "uvx, outside the wired npx-or-binary policy, so no wired claim. uvx "
        "minion-code@0.1.44 (`acp`); needs a uv bootstrap. AGPL-3.0.",
        source="https://github.com/femto/minion-code",
    ),
    # === vendor-locked: cannot route through the gateway ==================
    AcpAgent(
        registry_id="amp-acp",
        name="Amp",
        license="Apache-2.0",
        repository="https://github.com/tao12345666333/amp-acp",
        distribution=BINARY,
        package="",
        acp_args="",
        status=RUNNABLE,
        summary="Sourcegraph Amp over ACP.",
        reason="RUNNABLE: installs + launches headless, ACP handshake OK (smoke: "
        "initialize+session/new OK), but routes to its vendor backend — a thin "
        "wrapper over Amp (a managed Sourcegraph service): AMP_API_KEY only, no "
        "base-URL override, fixed curated model set (modes smart/deep/rush), so "
        "the benchmark's model can't be enforced through the gateway.",
        source="https://github.com/tao12345666333/amp-acp",
    ),
    AcpAgent(
        registry_id="auggie",
        name="Auggie CLI",
        license="proprietary",
        repository="https://github.com/augmentcode/auggie",
        distribution=NPX,
        package="@augmentcode/auggie",
        acp_args="--acp",
        status=RUNNABLE,
        summary="Augment Code's CLI over ACP.",
        reason="RUNNABLE: installs + launches headless and completes the ACP "
        "handshake (smoke: initialize+session/new OK), but routes to its vendor "
        "backend — needs an Augment account + `auggie login`; AUGMENT_API_URL "
        "targets Augment tenants only and the LLM call is server-side, so there is "
        "no BYO key/base URL and no gateway enforcement.",
        source="https://docs.augmentcode.com/cli/acp/clients",
    ),
    AcpAgent(
        registry_id="cortex-code",
        name="Cortex Code",
        license="proprietary",
        repository="https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code",
        distribution=BINARY,
        package="",
        acp_args="",
        status=RUNNABLE,
        summary="Snowflake Cortex Code over ACP.",
        reason="RUNNABLE: installs + launches headless, ACP handshake OK (smoke: "
        "initialize+session/new OK), but routes to its vendor backend — requires a "
        "Snowflake account + CORTEX_USER role; models run inside Snowflake Cortex, "
        "no BYO base URL, so no gateway enforcement.",
        source="https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code-cli",
    ),
    AcpAgent(
        registry_id="corust-agent",
        name="Corust Agent",
        license="GPL-3.0-or-later",
        repository="https://github.com/Corust-ai/corust-agent-release",
        distribution=BINARY,
        package="",
        acp_args="",
        status=RUNNABLE,
        summary="Corust's fine-tuned Rust agent over ACP.",
        reason="RUNNABLE: installs + launches headless, ACP handshake OK (smoke: "
        "initialize+session/new OK), but routes to its vendor backend — runs "
        "Corust's own fine-tuned model through a Corust-hosted gateway, no custom "
        "base URL or arbitrary model. Ships x86_64-only Linux binary (no arm64); "
        "GPL-3.0.",
        source="https://github.com/Corust-ai/corust-agent-release",
    ),
    AcpAgent(
        registry_id="cursor",
        name="Cursor",
        license="proprietary",
        repository="https://cursor.com/docs/cli",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=VENDOR_LOCKED,
        summary="Cursor CLI (cursor-agent) over ACP.",
        reason="BLOCKED headless (smoke-confirmed): session/new returns -32603 "
        "'Failed to initialize session services' with a dummy CURSOR_API_KEY; the "
        "only authenticate method is cursor_login (interactive browser OAuth), so "
        "no ACP session can be created without a real Cursor account.",
        source="https://cursor.com/docs/cli",
    ),
    AcpAgent(
        registry_id="factory-droid",
        name="Factory Droid",
        license="proprietary",
        repository="https://factory.ai",
        distribution=NPX,
        package="droid",
        acp_args="exec --output-format acp-daemon",
        status=RUNNABLE,
        summary="Factory's Droid agent over ACP.",
        reason="RUNNABLE: installs + launches headless, ACP handshake OK (smoke: "
        "initialize+session/new OK), but routes to its vendor backend — requires a "
        "Factory account; model selection and the LLM call are Factory-managed, no "
        "documented BYO base URL, so no gateway enforcement.",
        source="https://docs.factory.ai",
    ),
    AcpAgent(
        registry_id="glm-acp-agent",
        name="GLM Agent",
        license="Apache-2.0",
        repository="https://github.com/stefandevo/glm-acp-agent",
        distribution=NPX,
        package="glm-acp-agent@1.1.4",
        acp_args="",
        status=WIRED,
        summary="Z.AI GLM agent over ACP — OpenAI-Chat-Completions under the hood, "
        "base URL fully overridable via ACP_GLM_BASE_URL.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "ACP_GLM_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "Z_AI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "ACP_GLM_MODEL",
        },
        acp_model_format="bare",
        supports_acp_set_model=True,
        model_via="env",
        bin_name="glm-acp-agent",
        verified=(
            "ACP routing smoke (deepseek-v4-flash, mock gateway): 2 upstream "
            "/v1/chat/completions, initialize+session/new OK — wired by "
            "construction, no real-task reward claimed",
        ),
        reason="npx (glm-acp-agent@1.1.4; @agentclientprotocol/sdk + the OpenAI "
        "SDK). UNBLOCKED contrary to the old VENDOR_LOCKED note: it is purely "
        "OpenAI-Chat-Completions under the hood and its base URL is fully "
        "overridable via ACP_GLM_BASE_URL, so pointing it at the gateway routes "
        "ANY model unchanged (the key Z_AI_API_KEY is read lazily on first prompt, "
        "so initialize+session/new handshake with no key). Model arrives via "
        "ACP_GLM_MODEL env (session default) OR ACP set_model — unstable_"
        "setSessionModel accepts arbitrary ids (warns 'not in advertised list; "
        "using as-is') — sent bare on /v1/chat/completions.",
        source="https://github.com/stefandevo/glm-acp-agent",
    ),
    AcpAgent(
        registry_id="qoder",
        name="Qoder CLI",
        license="proprietary",
        repository="https://qoder.com",
        distribution=NPX,
        package="@qoder-ai/qodercli",
        acp_args="--acp",
        status=RUNNABLE,
        summary="Qoder's coding CLI over ACP.",
        reason="RUNNABLE: installs + launches headless (smoke: initialize OK; "
        "session/new did NOT return a sessionId), but routes to its vendor backend "
        "— auth only via `qodercli login` or a Qoder PAT, no arbitrary base URL, "
        "models are Qoder-managed, so no gateway enforcement.",
        source="https://docs.qoder.com/en/cli/sdk/authentication",
    ),
    AcpAgent(
        registry_id="sigit",
        name="siGit Code",
        license="Apache-2.0",
        repository="https://github.com/getsigit/sigit",
        distribution=BINARY,
        package="",
        acp_args="",
        status=RUNNABLE,
        summary="Local-inference coding agent over ACP.",
        reason="RUNNABLE: installs + launches headless (smoke: initialize+session/"
        "new OK) but runs a LOCAL GGUF model (Onde Inference) — 'runs on your "
        "machine, no API keys, no cloud round-trips', so there is no remote "
        "provider to route through the gateway and the model is not "
        "gateway-enforced.",
        source="https://github.com/getsigit/sigit",
    ),
    # === out-of-scope: not an LLM coding/eval agent =======================
    AcpAgent(
        registry_id="agoragentic-acp",
        name="Agoragentic",
        license="MIT",
        repository="https://github.com/rhein1/agoragentic-integrations",
        distribution=NPX,
        package="agoragentic-mcp",
        acp_args="--acp",
        status=OUT_OF_SCOPE,
        summary="An agent marketplace (174+ capabilities, paid in USDC on Base "
        "L2) exposed over ACP.",
        reason="Not a single LLM agent with a routable model — it's a "
        "marketplace/payments surface. Out of scope for model-enforced evals.",
        source="https://agoragentic.com",
    ),
)


# --- lookups & invariants --------------------------------------------------
BY_ID: dict[str, AcpAgent] = {a.registry_id: a for a in ACP_AGENTS}


def by_status(status: str) -> tuple[AcpAgent, ...]:
    """All catalog agents with the given status."""
    if status not in _STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return tuple(a for a in ACP_AGENTS if a.status == status)


def wired_agents() -> tuple[AcpAgent, ...]:
    """Agents this package actually registers into BenchFlow."""
    return by_status(WIRED)

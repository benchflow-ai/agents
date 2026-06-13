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
CATALOG = "catalog"
VENDOR_LOCKED = "vendor-locked"
OUT_OF_SCOPE = "out-of-scope"

_STATUSES = frozenset({NATIVE, WIRED, CATALOG, VENDOR_LOCKED, OUT_OF_SCOPE})

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
            if self.distribution != NPX:
                # This pass only wires npx agents (reuses BenchFlow's proven
                # _js_agent_install). uvx/binary wiring is future work.
                raise ValueError(f"{self.registry_id}: wired entries must be npx")
            if not self.bin_name:
                raise ValueError(f"{self.registry_id}: wired entry needs bin_name")
            if not self.env_mapping:
                raise ValueError(f"{self.registry_id}: wired entry needs env_mapping")
            if self.launch_env:
                # register.py launches wired agents with a plain command; constant
                # launch env isn't supported there yet (it would need to go through
                # register_agent's contract, not a fragile shell prefix). Keep
                # launch_env to catalog-tier recipes until a wired agent needs it.
                raise ValueError(
                    f"{self.registry_id}: launch_env on a wired entry is not "
                    "supported yet — wire it through register_agent, not a prefix"
                )


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
        status=CATALOG,
        summary="Block's general agent; broad provider support incl. any "
        "OpenAI-compatible host.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "GOOSE_MODEL",
        },
        model_via="env",
        reason="BYO via OPENAI_HOST + OPENAI_BASE_PATH (or a custom_providers "
        "JSON with base_url), GOOSE_PROVIDER=openai, GOOSE_MODEL. Needs a binary "
        "installer (Linux x86_64 + aarch64 releases exist) and a base-URL split "
        "into host+path, so not in this npx-only first pass.",
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
        status=CATALOG,
        summary="DevOps agent; BYO-LLM custom OpenAI-compatible endpoint. The "
        "one registry agent with a source-verified ACP session/set_model.",
        api_protocol="openai-completions",
        acp_model_format="provider/model",
        supports_acp_set_model=True,
        model_via="set_model",
        reason="BYO via ~/.stakpak/config.toml api_endpoint + model "
        "(provider-prefixed, e.g. anthropic/claude-...). Needs a binary "
        "installer + a config-file writer (no env-only base URL). Notably "
        "implements real session/set_model.",
        source="https://github.com/stakpak/agent",
    ),
    AcpAgent(
        registry_id="vtcode",
        name="VT Code",
        license="MIT",
        repository="https://github.com/vinhnx/VTCode",
        distribution=BINARY,
        package="",
        acp_args="",
        status=CATALOG,
        summary="Rust coding agent; [[custom_providers]] with arbitrary base_url.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via vtcode.toml [[custom_providers]] base_url + api_key_env "
        "+ models. Needs a binary installer + config-file writer.",
        source="https://github.com/vinhnx/vtcode",
    ),
    AcpAgent(
        registry_id="crow-cli",
        name="crow-cli",
        license="Apache-2.0",
        repository="https://github.com/crow-cli/crow-cli",
        distribution=BINARY,
        package="",
        acp_args="",
        status=CATALOG,
        summary="Vendor-agnostic agent; any OpenAI-compatible endpoint.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via ~/.crow/config.yaml provider/base_url/api_key/model "
        "(${ENV} interpolation). Needs a binary installer + config-file writer.",
        source="https://github.com/crow-cli/crow-cli",
    ),
    AcpAgent(
        registry_id="kimi",
        name="Kimi CLI",
        license="MIT",
        repository="https://github.com/MoonshotAI/kimi-cli",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=CATALOG,
        summary="Moonshot's Kimi CLI; openai_legacy provider type takes any "
        "OpenAI chat-completions host.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via config.toml [providers.<name>] type=openai_legacy + "
        "base_url + api_key (OPENAI_BASE_URL/OPENAI_API_KEY env overrides exist). "
        "Ships PyInstaller Linux binaries; needs binary installer + config writer.",
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
        status=CATALOG,
        summary="Mistral's agent; custom provider presets with api_style=openai "
        "+ arbitrary api_base. ACP via the vibe-acp binary.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via ~/.vibe/config.toml [[providers]] api_base + "
        "api_key_env_var. Ships a dedicated vibe-acp Linux binary; needs binary "
        "installer + config writer.",
        source="https://github.com/mistralai/mistral-vibe",
    ),
    AcpAgent(
        registry_id="kilo",
        name="Kilo",
        license="MIT",
        repository="https://github.com/Kilo-Org/kilocode",
        distribution=BINARY,
        package="",
        acp_args="acp",
        status=CATALOG,
        summary="Kilo Code CLI (OpenCode-based); @ai-sdk/openai-compatible "
        "adapter with arbitrary baseURL.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via config file provider.<id>.options.baseURL + top-level "
        "model ({env:VAR} substitution; KILO_API_KEY env). No documented "
        "env-only base URL — needs a config-file writer.",
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
        status=CATALOG,
        summary="BYO agent: 'use any OpenAI-compatible provider by providing the "
        "base URL and model ID.'",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_API_BASE",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        bin_name="dirac",
        model_via="flag",
        reason="npx, pure-JS — close to wireable. Held back to verify two "
        "details first: it reads OPENAI_API_BASE (not OPENAI_BASE_URL), and the "
        "model is a launch flag (--model) rather than an env var, so the launch "
        "command must interpolate $BENCHFLOW_PROVIDER_MODEL.",
        source="https://github.com/dirac-run/dirac",
    ),
    AcpAgent(
        registry_id="deepagents",
        name="DeepAgents",
        license="MIT",
        repository="https://github.com/langchain-ai/deepagentsjs",
        distribution=NPX,
        package="deepagents-acp",
        acp_args="",
        status=CATALOG,
        summary="LangChain 'deep agents'; BYO model via LangChain "
        "(init_chat_model provider:model strings).",
        api_protocol="openai-completions",
        acp_model_format="bare",
        supports_acp_set_model=True,  # advertises a "model" config option
        model_via="config-option",
        reason="npx, pure-JS, and advertises an ACP 'model' config option — but "
        "model ids are provider-prefixed with a COLON (e.g. openai:gpt-...), a "
        "format BenchFlow can't currently emit (it does bare / provider-slash / "
        "registered-provider-slash). Base URL rides the underlying LangChain "
        "client's OPENAI_BASE_URL. Wire once a colon format is supported.",
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
        status=CATALOG,
        summary="MCP-centric general agent framework; per-provider base_url "
        "overrides. A good 'not just coding' agent.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "OPENAI_API_KEY",
        },
        model_via="flag",
        reason="BYO via OPENAI_BASE_URL/ANTHROPIC_BASE_URL (config or OPENAI__ "
        "nested env) + --model. uvx-distributed, so it needs a uv bootstrap "
        "this npx-only first pass doesn't ship.",
        source="https://fast-agent.ai/acp/",
    ),
    AcpAgent(
        registry_id="autohand",
        name="Autohand Code",
        license="Apache-2.0",
        repository="https://github.com/autohandai/autohand-acp",
        distribution=NPX,
        package="@autohandai/autohand-acp",
        acp_args="",
        status=CATALOG,
        summary="BYO agent; works with OpenRouter, OpenAI, Bedrock, DeepSeek, "
        "Z.ai, local models. Optional account is telemetry-only.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via ~/.autohand/config.json provider/baseUrl/apiKey/model "
        "(AUTOHAND_CONFIG, AUTOHAND_MODEL). Needs a config-file writer.",
        source="https://github.com/autohandai/code-cli",
    ),
    AcpAgent(
        registry_id="nova",
        name="Nova",
        license="proprietary",
        repository="https://github.com/Compass-Agentic-Platform/nova",
        distribution=NPX,
        package="@compass-ai/nova",
        acp_args="acp",
        status=CATALOG,
        summary="BYO agent; reads standard provider keys + base-URL overrides "
        "(Compass platform is an optional routing layer).",
        api_protocol="anthropic-messages",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "ANTHROPIC_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "ANTHROPIC_API_KEY",
        },
        bin_name="nova",
        model_via="env",
        reason="npx — close to wireable via ANTHROPIC_BASE_URL or "
        "DEFAULT_OPENAI_BASE_URL + model env. Held back to first verify the "
        "optional Compass routing layer can be fully bypassed with raw "
        "ANTHROPIC_BASE_URL (it bundles @anthropic-ai/sdk).",
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
        status=CATALOG,
        summary="Popular coding agent; OpenAI-compatible routing exists but is "
        "currently fragile.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via `cline auth --provider openai-native --baseurl ... "
        "--modelid ...`, but multiple open issues report the custom base URL "
        "being ignored (calls still hit api.openai.com). Wire only after "
        "verifying requests actually reach the gateway.",
        source="https://github.com/cline/cline/blob/main/apps/cli/README.md",
    ),
    AcpAgent(
        registry_id="github-copilot-cli",
        name="GitHub Copilot",
        license="proprietary",
        repository="https://github.com/github/copilot-cli",
        distribution=NPX,
        package="@github/copilot",
        acp_args="--acp --stdio",
        status=CATALOG,
        summary="GitHub Copilot CLI; BYOK (own provider keys) is GA — NOT "
        "backend-locked.",
        api_protocol="openai-completions",
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "COPILOT_PROVIDER_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "COPILOT_PROVIDER_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "COPILOT_MODEL",
        },
        launch_env={"COPILOT_PROVIDER_TYPE": "openai"},
        bin_name="copilot",
        model_via="env",
        reason="BYO via COPILOT_PROVIDER_BASE_URL/_TYPE/_API_KEY + COPILOT_MODEL "
        "(all env — would be wireable). Held back for two reasons: the npm "
        "package is an npm-loader that fetches a platform binary at runtime (the "
        "_js_agent_install `node <bin>` wrapper may not apply), and BYOK-in-ACP "
        "was broken <=1.0.60 (fixed ~1.0.61) — must pin + smoke-test session/new.",
        source="https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-byok-models",
    ),
    AcpAgent(
        registry_id="codebuddy-code",
        name="Codebuddy Code",
        license="proprietary",
        repository="https://www.codebuddy.ai",
        distribution=NPX,
        package="@tencent-ai/codebuddy-code",
        acp_args="--acp",
        status=CATALOG,
        summary="Tencent's coding agent; models.json supports fully custom "
        "OpenAI-format models (the BYO escape hatch).",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via models.json url + apiKey (${ENV} refs), CODEBUDDY_API_KEY. "
        "Default first run wants a Tencent login. Needs a config-file writer; "
        "chat-completions only.",
        source="https://www.codebuddy.ai/docs/cli/acp",
    ),
    AcpAgent(
        registry_id="dimcode",
        name="DimCode",
        license="proprietary",
        repository="https://dim.qwenkimi.com",
        distribution=NPX,
        package="dimcode",
        acp_args="acp",
        status=CATALOG,
        summary="BYO agent ('OpenAI, Anthropic, or custom endpoint'; bring your "
        "own model).",
        model_via="config-file",
        reason="BYO via `dim provider add --base-url --api-key --model` "
        "(~/.dimcode/v2/providers.json) — no LLM-routing env vars, so it needs a "
        "config-file writer. Per-provider wire protocol undocumented (binary is "
        "minified/closed).",
        source="https://dim.qwenkimi.com/docs/",
    ),
    AcpAgent(
        registry_id="grok-build",
        name="Grok Build",
        license="proprietary",
        repository="https://x.ai/cli",
        distribution=BINARY,
        package="",
        acp_args="",
        status=CATALOG,
        summary="xAI's Grok CLI; surprisingly BYO — GROK_MODELS_BASE_URL routes "
        "all requests through a gateway (e.g. Vercel AI Gateway).",
        api_protocol="openai-completions",
        model_via="env",
        reason="BYO via GROK_MODELS_BASE_URL + per-model config (base_url/env_key). "
        "Held back: proprietary, access-gated (SuperGrok/Premium+), and "
        "shell-installer-only (no public per-arch release page), though the "
        "installer fetches both Linux arches.",
        source="https://docs.x.ai/build",
    ),
    AcpAgent(
        registry_id="junie",
        name="Junie",
        license="proprietary",
        repository="https://github.com/JetBrains/junie",
        distribution=BINARY,
        package="",
        acp_args="",
        status=CATALOG,
        summary="JetBrains Junie CLI; 'the LLM-agnostic coding agent' — "
        "custom-model JSON profiles with arbitrary baseUrl.",
        api_protocol="openai-completions",
        model_via="config-file",
        reason="BYO via $JUNIE_HOME/models/*.json (id/baseUrl/apiType/apiKey) + "
        "--model custom:<id>. Needs a binary (shell-installer) + JSON writer. "
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
        status=CATALOG,
        summary="Poolside 'pool' CLI; connects to any OpenAI-compatible chat "
        "completions API (incl. LiteLLM, OpenRouter, Ollama).",
        api_protocol="openai-completions",
        model_via="env",
        reason="BYO via POOLSIDE_API_URL / --api-url + --model. Needs a binary "
        "(shell-installer) path; CLI binary is proprietary.",
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
        status=CATALOG,
        summary="Python coding agent over ACP (uvx-distributed).",
        model_via="config-file",
        reason="uvx-distributed (needs a uv bootstrap). BYO provider config "
        "UNCONFIRMED from public docs — confirm before wiring. AGPL-3.0.",
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
        status=VENDOR_LOCKED,
        summary="Sourcegraph Amp over ACP.",
        reason="Thin wrapper over Amp, a managed Sourcegraph service: AMP_API_KEY "
        "only, no base-URL override, fixed curated model set (modes "
        "smart/deep/rush). Cannot enforce the benchmark's model.",
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
        status=VENDOR_LOCKED,
        summary="Augment Code's CLI over ACP.",
        reason="Requires an Augment account + `auggie login`. AUGMENT_API_URL "
        "targets Augment tenants only; the LLM call is server-side. No BYO key "
        "or base URL.",
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
        status=VENDOR_LOCKED,
        summary="Snowflake Cortex Code over ACP.",
        reason="Requires a Snowflake account + CORTEX_USER role; models run "
        "inside Snowflake Cortex. No BYO base URL.",
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
        status=VENDOR_LOCKED,
        summary="Corust's fine-tuned Rust agent over ACP.",
        reason="Runs Corust's own fine-tuned model through a Corust-hosted "
        "gateway; no custom base URL or arbitrary model. Also ships no arm64 "
        "Linux binary (x86_64 only) and is GPL-3.0.",
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
        reason="Headless cursor-agent routes only through Cursor's backend "
        "(requires a Cursor account). The app's custom-OpenAI-base-URL BYOK is "
        "chat-models-only and does not reach the CLI.",
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
        status=VENDOR_LOCKED,
        summary="Factory's Droid agent over ACP.",
        reason="Requires a Factory account; model selection and the LLM call are "
        "Factory-managed. No documented BYO base URL.",
        source="https://docs.factory.ai",
    ),
    AcpAgent(
        registry_id="glm-acp-agent",
        name="GLM Agent",
        license="Apache-2.0",
        repository="https://github.com/stefandevo/glm-acp-agent",
        distribution=NPX,
        package="glm-acp-agent",
        acp_args="",
        status=VENDOR_LOCKED,
        summary="Z.AI GLM agent over ACP.",
        reason="A base-URL var (ACP_GLM_BASE_URL) exists, but the README states "
        "it is built for the Z.AI GLM Coding Plan and the endpoint rejects any "
        "model Z.AI hasn't whitelisted — effectively locked to GLM models.",
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
        status=VENDOR_LOCKED,
        summary="Qoder's coding CLI over ACP.",
        reason="Auth only via `qodercli login` or a Qoder PAT; no arbitrary base "
        "URL. Models are Qoder-managed.",
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
        status=VENDOR_LOCKED,
        summary="Local-inference coding agent over ACP.",
        reason="'Runs on your machine. No API keys. No cloud round-trips' — "
        "downloads a local GGUF model (Onde Inference). No remote-provider "
        "concept at all, so nothing to route through the gateway.",
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

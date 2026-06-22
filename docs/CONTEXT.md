# CONTEXT — benchflow-ai/agents (decoupled agent contract)

Glossary for the design that moves agent integrations out of benchflow **core**
(`src/benchflow/agents/`) into the standalone **benchflow-ai/agents** repo, behind one
unified contract, so benchflow can host naive ACP / ai-sdk / omnigent agents and still
capture raw-LLM trajectories + token usage via its LiteLLM proxy — behaving identically to
the vanilla platforms.

> This is a glossary only. Decisions live in `adr/`. Destined for the benchflow-ai/agents
> repo root (its `docs/` already holds `parity.md`, `adaptation.md`).

## Terms

### Unified agent contract
The single interface an agent must satisfy to be hosted. **Two halves:** (1) a **process that
speaks ACP JSON-RPC over stdio** (the drive contract) and (2) the **capture contract** —
routing all model calls through the injected proxy. Declared by a **manifest** + the agent's
own shim/skills directory. There is no second protocol.

### Host kind
How benchflow runs an agent. **Exactly one** — an ACP-over-stdio process. Non-ACP platforms
are wrapped in a **shim**, never given a separate protocol.

### Manifest
The eve-style declarative, code-free description of an agent (`manifest.toml`) in its own
directory: `install_cmd`, `launch_cmd` (an ACP-over-stdio process), `env_mapping`,
`acp_model_format`, model defaults, skill/credential paths. Core **scans a discovery dir**
and parses manifests into the internal `AgentConfig`. No agent Python runs in core's process.

### Shim
A thin, behavior-free adapter shipped in an agent's directory that (a) presents a non-ACP
agent as an ACP-over-stdio process and/or (b) translates the canonical proxy env vars into
the underlying tool's required config **file** (e.g. mimo → `mimocode.json`). Runs in the
sandbox, never in core.

### Naive agent
An integration that adds **no benchflow-specific logic to the agent itself** — it behaves as
on its native platform; benchflow observes it externally at the capture boundary.
_Not_ a fork/patch of the upstream agent.

### Capture boundary
The single point where benchflow observes an agent's model traffic: the **LiteLLM proxy**
that every model call traverses. Raw request/response bodies + token usage are reconstructed
here. **Fail-closed:** core strips all upstream provider secrets (the agent can reach *only*
the proxy) and `usage_tracking=required` (a capture miss fails the run, never a silent
untracked result).

### env_mapping
The declarative rename table in a manifest (`BENCHFLOW_PROVIDER_BASE_URL → OPENAI_BASE_URL`,
…). Covers OpenAI/Anthropic/LLM_*-surface tools as pure data. Tools needing a config *file*
use a shim instead. Core never branches per-agent.

### Vanilla
**The agent run standalone on its native platform** — _not_ benchflow's in-core agent. The
baseline for equivalence.

### Vanilla equivalence
The property, asserted by **wire-parity**: the upstream LLM requests benchflow's hosted agent
emits are **byte-identical** to the vanilla (standalone) agent's, modulo an explicit
neutral-diff allowlist (proxy model-alias rename, sandbox cwd, trailing whitespace,
`content:null`-vs-omitted), plus **outcome parity** (same reward + tool sequence; token counts
may vary within sampling noise). Asserted by a per-package offline pytest against a recorded
fixture.

### Discovery dir
The directory core scans for manifests at startup — the externalized replacement for the
compiled-in `AGENTS` dict. **Populated by** the `benchflow-agents` pip package (the `agents/`
tree shipped as package data; resolved via `importlib.resources`), with a `BENCHFLOW_AGENTS_DIR`
env override pointing at a local checkout for development.

### Contract version
The SemVer the contract `{manifest schema + ACP + proxy-env}` is at. Each manifest declares a
`contract_version`; core declares a supported range and skips/rejects out-of-range manifests
with a clear error. The `benchflow-agents` package also pins `benchflow>=N` as a backstop.

## Flagged ambiguities (resolved)

- "vanilla" meant both *benchflow's in-core mimo agent* (old VM fingerprint check) and *the
  agent standalone on its native platform* (parity.md) → **resolved: standalone native
  platform** is canonical.
- "the unified contract" was used for both the kernel-facing Agent/Session Protocol and the
  agent-facing proxy-env contract → **resolved: the contract is ACP-over-stdio + the
  proxy-env capture contract**, declared via a manifest.

# 0001 — Unified agent contract: one ACP-over-stdio protocol, manifest discovery, fail-closed proxy capture

- Status: Accepted (design grilling 2026-06-17)
- Deciders: Yimin (repo owner)
- Context repo: benchflow-ai/agents (decoupling from benchflow core `src/benchflow/agents/`)

## Context

Today an agent is hostable only by being a `AgentConfig` entry in the compiled-in `AGENTS`
dict in benchflow core's `registry.py`, with per-agent shims (openclaw 884L, etc.) shipped
inside `src/benchflow/agents/`, and per-agent `if agent == …` branches in
`providers/litellm_runtime._apply_litellm_agent_env`, `agents/env.py`, and
`acp/runtime._format_acp_model`. 23 core modules import `benchflow.agents.*`. Adding an agent
requires a core edit + release. The goal is to host agents from a **separate repo**
(benchflow-ai/agents) behind one contract, capturing raw-LLM trajectories + token usage via
the LiteLLM proxy, behaving identically to the vanilla platforms.

The agents repo already proves (PR8/9/10) that even a CLI agent (MiMo Code) can be hosted
behind a pure **ACP-over-stdio shim** with zero kernel change and `usage_source=provider_response`
capture identical to a vanilla baseline.

## Decision

1. **One protocol.** The contract is a process that speaks **ACP JSON-RPC over stdio** plus
   the **proxy-env capture contract**. Non-ACP platforms (omnigent) are wrapped in a thin
   ACP-stdio shim exactly as ai-sdk wraps MiMo. The `session-factory` CONNECT seam is
   **dropped** — `feat/session-factory-seam` and its re-port are abandoned; the kernel gains
   no new `connect_*` branch.
2. **Filesystem manifest discovery (eve-style).** Each agent is a self-contained directory in
   benchflow-ai/agents: `manifest.toml` (data only) + shim code + skills. Core scans a
   discovery dir and parses manifests into `AgentConfig`. No agent Python runs in core's
   process. The `AGENTS` dict and per-agent shims leave core.
3. **Hybrid translation.** Manifest `env_mapping` expresses simple variable renames
   declaratively (covers OpenAI/Anthropic/LLM_*-surface tools); tools needing a config *file*
   (mimo→`mimocode.json`, codex→`CODEX_CONFIG`) ship a shim in their own dir. Core's per-agent
   if-ladder is deleted — core applies `env_mapping` generically and never branches per agent.
4. **Fail-closed capture.** Core strips all upstream provider secrets (the agent can reach
   *only* the LiteLLM proxy) and sets `usage_tracking=required`, so a misrouted shim fails the
   run loudly instead of producing a silent untracked (0-token) result.
5. **Thin loader in core, target the default branch.** Target `codex/lightweight-task-authoring`
   (the import-free refactored kernel, where releases ship). Core keeps the host machinery
   (ACP client/transport/session, the LiteLLM proxy + capture, rollout planes) and the
   versioned manifest schema; `registry.py` becomes a generic manifest loader. Everything
   agent-specific lives in benchflow-ai/agents.

## Consequences

- **PR10 unblocked.** omnigent-mimo stops being a `session-factory` agent and becomes an
  ACP-stdio shim — package-local work, no benchflow-core seam to re-author.
- Adding an agent = a manifest + shim in benchflow-ai/agents; **no core release**.
- Core's residual agent surface shrinks to: manifest schema + loader, the ACP stack, the
  proxy/capture, and the rollout planes.
- The contract `{manifest schema + ACP + proxy-env}` must be **versioned** so an external
  agent bundle can't silently break against a newer/older core.
- Capture is structurally guaranteed (no off-proxy path; required tracking).

## Alternatives considered

- **Two protocols (ACP + session-factory).** Rejected: requires re-authoring
  `_connect_session_factory` against the flat-module branch (the current PR10 blocker) and
  maintaining two vanilla-equivalent host paths, for no capability the ACP shim lacks.
- **One Protocol object, two adapters.** Rejected: keeps kernel import-free but still requires
  building+porting a session-factory adapter — no PR10 relief, more abstraction.
- **Python entry-points / import-time `register_agent`.** Rejected in favor of filesystem
  manifests (eve model): keeps the declaration pure data, language-agnostic, with no
  import-time side effects in core.
- **Rich declarative schema that emits config files from core.** Rejected: grows a
  templating/file-emit engine in core; the shim keeps that complexity in the agent's dir.
- **Build on the old `rollout/`-package branch.** Rejected: throwaway port against a kernel
  structure already replaced on the default branch.

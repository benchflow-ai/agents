# Adapting an agent to BenchFlow

An agent becomes a BenchFlow agent by speaking **ACP over stdio**, registered one of
two ways: via the public `register_agent` extension point — the **code path**, for an
agent that needs a shim/adapter to speak ACP — **or** via a declarative
`acp/<id>/manifest.toml` — for an agent that already speaks ACP, discovered by the
`contract/` manifest loader with no code of its own. The code path is now the
minority: 38 of the 40 `acp/` entries are declarative manifests. Either way the
integration lives in this repo, not baked into the framework; the same runtime is
used in production, so there is no eval-only reimplementation (that's the
[eval↔prod-gap](../README.md) point).

BenchFlow sorts adapted agents into six **tiers** — `wired` · `runnable` · `catalog`
· `native` · `vendor-locked` · `out-of-scope` — by how much of a run it captures:
`wired`/`native` get both the raw-LLM proxy trajectory and the ACP logs, `runnable`
gets the ACP logs only. See [tiers.md](tiers.md) for the tier model + the per-tier
log semantics, and [`acp-registry/AGENTS.md`](../acp-registry/AGENTS.md) for the live
tally and per-agent table.

Worked examples: [`ai-sdk/acp`](../ai-sdk/acp) (AI SDK `ToolLoopAgent`),
[`ai-sdk/harness-pi`](../ai-sdk/harness-pi) (AI SDK 7 `HarnessAgent`),
[`mini-swe-acp`](../acp/mini-swe-acp) (a Python harness shim).

## Two files

**`server.mjs`** — a pure-JS ACP-over-stdio server (or a Python shim). Rules:
- Newline-delimited JSON-RPC 2.0; **stdout = protocol only**, all logs → stderr.
- Handle `initialize`, `session/new` (capture cwd), `session/set_model` (store the
  model id; reply `{}`), `session/prompt` (run the agent loop, stream
  `session/update` events, reply `{stopReason, usage}`), `session/cancel` (abort).
- Map the agent's stream → ACP: text → `agent_message_chunk`, reasoning →
  `agent_thought_chunk`, tool call → `tool_call` (name + args in `title`, since the
  ACP wire has no input field), tool result → `tool_call_update`.
- Route the model at `OPENAI_BASE_URL` (BenchFlow's gateway) so usage is captured
  and the benchmark's model is enforced. This is the **wired/native** bar; the
  general adaptation floor is looser — *BenchFlow can create the experiment AND
  track the run's logs* — so **runnable** agents are adapted *without* gateway
  routing (the model runs on the agent's own/vendor backend, leaving only the
  ACP-trajectory logs). See [tiers.md](tiers.md).
- Dispatch on `rl.on("line")` (not a blocking `for await`) so `session/cancel`
  is delivered mid-prompt.

**`register.py`** — `register_agent(name, install_cmd, launch_cmd, protocol="acp",
api_protocol=..., env_mapping={BENCHFLOW_PROVIDER_*: agent vars},
acp_model_format="bare", requires_env=[])`. `install_cmd` bootstraps node,
base64-deploys `server.mjs`, and npm-installs deps **in the sandbox**;
`launch_cmd` scrubs latent env (`NODE_OPTIONS`, proxy/TLS) and runs the server.

## Manifest-only path

For an agent that already speaks ACP, neither `server.mjs` nor `register.py` is
written — adaptation is a single declarative `acp/<id>/manifest.toml`. It carries
`contract_version`, `install_cmd`, `launch_cmd`, `protocol`, `api_protocol`,
`acp_model_format`, `supports_acp_set_model`, and an `[env_mapping]` from
`BENCHFLOW_PROVIDER_*` to the agent's own env vars. Its tier is classified in
[`catalog.py`](../acp-registry/src/acp_registry/catalog.py); the manifest is loaded
and validated by `contract/`. This is now the majority of the registry — see
[`acp-registry/AGENTS.md`](../acp-registry/AGENTS.md). Worked examples:
[`acp/goose/manifest.toml`](../acp/goose/manifest.toml) (wired — per-arch binary) and
[`acp/fast-agent/manifest.toml`](../acp/fast-agent/manifest.toml) (runnable — uvx).

## Sandbox notes (harness agents)

A wrapped harness may run the agent in its own session working dir; bridge it to
BenchFlow's task cwd (pre-seed task files in, sync results back, and symlink so
absolute `/app` paths resolve — see `ai-sdk/harness-pi`). **Bridge-backed**
harnesses (Codex, Claude Code) need a port-exposing (Vercel) sandbox and can't run
on the local just-bash sandbox — use BenchFlow's native `codex-acp` /
`claude-agent-acp` instead.

## Then: verify parity

Adapting isn't done until you've shown the agent behaves the same inside BenchFlow
as standalone. See [parity.md](parity.md) and
[`skills/adaptation-parity`](../skills/adaptation-parity).

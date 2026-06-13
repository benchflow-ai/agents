# Adapting an agent to BenchFlow

An agent becomes a BenchFlow agent by speaking **ACP over stdio** and registering
via the public `register_agent` extension point — so the integration lives in this
repo, not baked into the framework. The same runtime is used in production; there
is no eval-only reimplementation (that's the [eval↔prod-gap](../README.md) point).

Worked examples: [`ai-sdk/acp`](../ai-sdk/acp) (AI SDK `ToolLoopAgent`),
[`ai-sdk/harness-pi`](../ai-sdk/harness-pi) (AI SDK 7 `HarnessAgent`),
[`mini-swe-acp`](../mini-swe-acp) (a Python harness shim).

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
  and the benchmark's model is enforced.
- Dispatch on `rl.on("line")` (not a blocking `for await`) so `session/cancel`
  is delivered mid-prompt.

**`register.py`** — `register_agent(name, install_cmd, launch_cmd, protocol="acp",
api_protocol=..., env_mapping={BENCHFLOW_PROVIDER_*: agent vars},
acp_model_format="bare", requires_env=[])`. `install_cmd` bootstraps node,
base64-deploys `server.mjs`, and npm-installs deps **in the sandbox**;
`launch_cmd` scrubs latent env (`NODE_OPTIONS`, proxy/TLS) and runs the server.

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

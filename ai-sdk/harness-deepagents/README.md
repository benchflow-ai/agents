# ai-sdk-deepagents

The **[Vercel AI SDK 7 `HarnessAgent`](https://ai-sdk.dev/v7/providers/ai-sdk-harnesses)**
running the **DeepAgents** harness, as a [BenchFlow](https://github.com/benchflow-ai/benchflow)
agent over [ACP](https://github.com/zed-industries/agent-client-protocol). deepagents
is a JS agent loop, so — like [`harness-pi`](../harness-pi) — it runs **in-process**
on the local `@ai-sdk/sandbox-just-bash` sandbox (no port-exposing bridge), inside
benchflow's task sandbox on the real task files. `server.mjs` is the same ACP framing
+ `fullStream`→ACP mapping + session-dir↔task-cwd bridge as `harness-pi`, but builds
the agent with `createDeepAgents()`. (deepagents also ships as a benchflow-native ACP
agent, `deepagents`; this is the AI-SDK-harness variant of the same loop.)

**Status** — Scaffolded — wraps `@ai-sdk/harness-deepagents`; runs the AI SDK 7
HarnessAgent. Model routing + wire-parity NOT yet verified (next step).

## Dev

```bash
cd ai-sdk/harness-deepagents
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q                                        # key-free; no sandbox/model needed
ruff check src tests
node --check src/ai_sdk_harness_deepagents/server.mjs
```

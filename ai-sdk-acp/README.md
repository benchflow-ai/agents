# ai-sdk-acp

A **Vercel AI SDK** [`ToolLoopAgent`](https://ai-sdk.dev/docs/agents/building-agents)
exposed as a [BenchFlow](https://github.com/benchflow-ai/benchflow) agent over
[ACP](https://github.com/zed-industries/agent-client-protocol).

It's a compact pure-JS ACP-over-stdio server (`server.mjs`) wrapping the AI SDK's
tool loop, plus `register.py` that wires it into BenchFlow through the public
`register_agent` extension point — so the integration lives here, not baked into
the framework.

## Why a thin AI-SDK bridge

The AI SDK abstracts over provider wire-protocols, so a single agent can route to
DeepSeek (completions), OpenAI, or Anthropic without per-harness lock-in. The bridge
is pure-JS (no native launcher quirks), points its model client at BenchFlow's
gateway `baseURL`, and maps the AI SDK `fullStream` onto ACP `session/update`
events — so trajectory + token usage are captured the same as any other agent.

## How it routes

```
server.mjs ──▶ OPENAI_BASE_URL (BenchFlow LiteLLM gateway) ──▶ provider
```

`register.py` sets `api_protocol="openai-completions"` and maps
`BENCHFLOW_PROVIDER_BASE_URL → OPENAI_BASE_URL` / `BENCHFLOW_PROVIDER_API_KEY →
OPENAI_API_KEY`. The model id arrives bare via `session/set_model` and is forwarded
straight to the provider (no model registry to satisfy). `includeUsage: true` makes
the AI SDK report real token counts in the `finish` part, surfaced back over ACP.

## Quickstart

```python
from ai_sdk_acp.register import register
register()  # adds the "ai-sdk" agent (aliases: aisdk, vercel-ai-sdk)

import asyncio
from benchflow.runtime import run, Agent, Environment, RuntimeConfig

async def main():
    env = Environment.from_task("path/to/task", sandbox="daytona")
    res = await run(Agent("ai-sdk", "deepseek/deepseek-v4-flash"), env, RuntimeConfig())
    print(res.rollout_dir)

asyncio.run(main())
```

## Inside == outside (behavioral parity)

The server is hardened so it behaves identically inside BenchFlow and standalone:

- **Env-independent system prompt** — the working directory is *not* baked into the
  prompt (it differs between sandbox `/app` and a local dir).
- **Latent env scrubbed** — `HTTP(S)_PROXY` / `NO_PROXY` / `NODE_TLS_REJECT_UNAUTHORIZED`
  (in-process) and `NODE_OPTIONS` (in `launch_cmd`) are stripped so outbound model
  HTTP/TLS is deterministic.
- **Watchdog keepalive** — during long, output-silent tool runs the server emits a
  periodic `tool_call_update{in_progress}` (every `BF_HEARTBEAT_MS`, default 10s) so
  BenchFlow's idle watchdog doesn't cancel a working agent.

Verified: with the gateway in the path, the upstream request is byte-identical to a
standalone run (same system+user prompt, tools, and sampling params) modulo the
gateway's own neutral artifacts (model-alias rename; `content:null` vs omitted from
LiteLLM stream re-aggregation).

### Notes / known residuals

- **Cost** is `null` unless pricing is configured — neither the AI SDK (tokens only)
  nor the gateway computes `$` for a custom DeepSeek route. Register
  `input_cost_per_token`/`output_cost_per_token` in the gateway's `model_info` to fill it.
- **`drop_params`**: the gateway runs with `drop_params:True`, which silently drops
  params a provider doesn't support. Standard sampling params
  (`temperature/top_p/seed/penalties/max_tokens/stop`) are verified to pass through;
  vendor-specific params may be dropped.
- **Native usage**: the agent also reports usage over ACP (`agent_native_acp`); when
  the gateway is in the path, the proxy's `provider_response` usage takes precedence.

## Dev

```bash
cd ai-sdk-acp
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q                                        # key-free; no sandbox/model needed
ruff check src tests
```

# mimo-acp

[MiMo Code](https://mimo.xiaomi.com/mimocode) (Xiaomi) as a
[BenchFlow](https://github.com/benchflow-ai/benchflow) agent — registered
out-of-core through the public `benchflow.register_agent` extension point.

MiMo Code is an **OpenCode fork** whose `mimo` CLI ships a **native** ACP
server (`mimo acp`, JSON-RPC over stdio). So — unlike the `ai-sdk/harness-*`
packages, which implement the ACP server in a JS `server.mjs` wrapping a Vercel
AI SDK agent — this package ships **no** `server.mjs`: `mimo acp` *is* the
server. Structurally it mirrors [`mini-swe-acp`](../mini-swe-acp/) (a native
agent registered out-of-core), minus the custom Python ACP shim.

```
benchflow eval  ──ACP/stdio──▶  mimo acp   (native server, npm @mimo-ai/cli)
        │                            │
        └─ set_model openai/<alias>  └─ mimocode.json: provider "openai"
                                        → $OPENAI_BASE_URL (LiteLLM proxy)
                                        → wire-level raw LLM captured
```

## Install

```bash
pip install "mimo-acp @ git+https://github.com/benchflow-ai/agents#subdirectory=mimo-acp"
```

```python
import mimo_acp  # importing registers the `mimo` agent (alias: `mimo-code`)
from benchflow import SDK

# validated path: any gateway-routed model through BenchFlow's LiteLLM proxy,
# with wire-level raw-LLM capture in trajectory/llm_trajectory.jsonl:
await SDK().run(
    task_path="...", agent="mimo",
    model="deepseek/deepseek-v4-flash",   # any benchflow-proxied model
    usage_tracking="auto",                # proxy mode → raw LLM captured
)
```

The free, no-account **`mimo/mimo-auto`** channel also works in-sandbox (no key,
`usage_tracking="off"`) — but it routes to MiMo's own backend, so there is *no*
LiteLLM proxy in the path and *no* `llm_trajectory.jsonl`. Use it for a quick
key-free smoke test; use the proxy path above when you need raw-LLM capture.

## Proxy mode (raw-LLM capture) — how it works

To capture wire-level raw LLM the agent's model calls must traverse BenchFlow's
LiteLLM usage proxy. BenchFlow drives model selection over standard ACP
`session/set_model`, and for a `benchflow-…` proxy alias with
`acp_model_format="provider/model"` it emits **`openai/<alias>`** (the only
prefix the proxy registers; see benchflow `acp/runtime.py::_format_acp_model`).
So `register.py` makes the launcher's `mimocode.json` register a **custom
OpenAI-compatible provider under the key `openai`** that points at the proxy
(`$OPENAI_BASE_URL`) and carries a `models` map keyed **exactly** by the bare
alias — so `openai/<alias>` resolves. Without this, mimo raises
`ProviderModelNotFoundError` and the turn captures **zero** LLM requests.

Because mimo's built-in `openai` provider auto-activates from `OPENAI_*` env and
would then collide with this redefine (a silent zero-token turn), the launcher
**unsets `OPENAI_BASE_URL`/`OPENAI_API_KEY` after** baking them into the config.

- `register.py` registers `mimo` with `protocol="acp"`,
  `api_protocol="openai-completions"`, **`acp_model_format="provider/model"`**,
  `supports_acp_set_model=True`, and an `env_mapping` that lands the resolved
  gateway URL/key in `OPENAI_BASE_URL`/`OPENAI_API_KEY` (the same
  OpenAI-compatible contract as [`ai-sdk/acp`](../ai-sdk/acp/)).
- `install_cmd` bootstraps BenchFlow's isolated Node and `npm install`s the
  pinned `@mimo-ai/cli@0.1.1` into `/opt/benchflow/js-agents/mimo-acp`.
- `launch_cmd` writes the proxy `mimocode.json` (custom `openai` provider →
  `$OPENAI_BASE_URL`, models keyed by `$BENCHFLOW_LITELLM_MODEL_ALIAS`), unsets
  the colliding `OPENAI_*` env, then `exec`s `node …/@mimo-ai/cli/bin/mimo acp`.

**Gotcha:** MiMo's ACP `initialize` reports `agentInfo.name="OpenCode"` (the
upstream fork name). The BenchFlow-side agent name is `mimo` (the registry key)
and is independent of that wire value.

## Models

| model | key | notes |
|---|---|---|
| `deepseek/deepseek-v4-flash` (and any benchflow-proxied model) | gateway URL/key via `OPENAI_BASE_URL`/`OPENAI_API_KEY` | **validated path** — `provider/model` + custom `openai` provider in `mimocode.json` routes through the LiteLLM proxy; raw LLM captured (`usage_source=provider_response`) |
| `mimo/mimo-auto` | none | free no-account channel; headless, in-sandbox smoke test — routes to MiMo's backend, **no proxy, no raw-LLM trajectory** |
| `xiaomi/mimo-v2.5-pro` | `XIAOMI_API_KEY` + `XIAOMI_BASE_URL` | flagship; can also run via the native `mimo` agent in benchflow core ([PR #679](https://github.com/benchflow-ai/benchflow/pull/679)) |

## Dev

```bash
uv venv --python 3.12 && . .venv/bin/activate
uv pip install benchflow pytest ruff && uv pip install -e . --no-deps
pytest -q
ruff check src tests && ruff format --check src tests
```

Live evidence: a fresh Daytona proxy eval of **`deepseek/deepseek-v4-flash`**
through *this package* on `citation-check` lands **reward 1.0**, **7 tool
calls**, `usage_source=provider_response`, and a `trajectory/llm_trajectory.jsonl`
with multiple `deepseek-v4-flash` status-200 **agent turns** (each carrying the
`You are MiMoCode …` system prompt + the 14 tool defs) — a genuine tool-using
run, not just the OpenCode title-generator call. This raw-LLM capture is the
`provider/model` + custom-`openai`-provider wiring in *this* package's launcher.

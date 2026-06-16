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
```

## Install

```bash
pip install "mimo-acp @ git+https://github.com/benchflow-ai/agents#subdirectory=mimo-acp"
```

```python
import mimo_acp  # importing registers the `mimo` agent (alias: `mimo-code`)
from benchflow import SDK

# free, no-account channel — no key needed (this package's validated path):
await SDK().run(task_path="...", agent="mimo", model="mimo/mimo-auto")
```

For MiMo's flagship **`xiaomi/mimo-v2.5-pro`**, use the *native `mimo` agent in
benchflow core* ([PR #679](https://github.com/benchflow-ai/benchflow/pull/679)):
it sets `acp_model_format="provider/model"` + writes a `mimocode.json`
credential file, which keeps the `xiaomi/` provider prefix intact. This
out-of-core package uses `acp_model_format="bare"` (so `mimo/mimo-auto` passes
through), and `bare` *strips* the `xiaomi/` prefix — so the native-xiaomi route
is not reliably available here.

## How it works

- `register.py` registers `mimo` with `protocol="acp"`,
  `api_protocol="openai-completions"`, `acp_model_format="bare"`, and an
  `env_mapping` that lands the resolved gateway URL/key in
  `OPENAI_BASE_URL`/`OPENAI_API_KEY` (the same OpenAI-compatible contract as
  [`ai-sdk/acp`](../ai-sdk/acp/)).
- `install_cmd` bootstraps BenchFlow's isolated Node and `npm install`s the
  pinned `@mimo-ai/cli@0.1.1` into `/opt/benchflow/js-agents/mimo-acp`.
- `launch_cmd` runs `node …/@mimo-ai/cli/bin/mimo acp`.

**Gotcha:** MiMo's ACP `initialize` reports `agentInfo.name="OpenCode"` (the
upstream fork name). The BenchFlow-side agent name is `mimo` (the registry key)
and is independent of that wire value.

## Models

| model | key | notes |
|---|---|---|
| `mimo/mimo-auto` | none | free no-account channel; headless, works in-sandbox — **this package's validated path** |
| `xiaomi/mimo-v2.5-pro` | `XIAOMI_API_KEY` + `XIAOMI_BASE_URL` | flagship — use the native `mimo` agent in benchflow core (`bare` strips the `xiaomi/` prefix here) |

## Dev

```bash
uv venv --python 3.12 && . .venv/bin/activate
uv pip install benchflow pytest ruff && uv pip install -e . --no-deps
pytest -q
ruff check src tests && ruff format --check src tests
```

Live evidence: the free **`mimo/mimo-auto`** channel runs healthy end-to-end
through this package (native `mimo acp`, in-sandbox). The flagship
**`xiaomi/mimo-v2.5-pro`** reward-1.0 / 17-tool-call `citation-check` result was
the *native `mimo` agent in benchflow core* (which has the `provider/model` +
`mimocode.json` wiring), **not** this out-of-core `bare` package.

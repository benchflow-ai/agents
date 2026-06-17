# ai-sdk/harness-mimo

Vercel **AI SDK 7 `HarnessAgent`** driving [MiMo Code](https://mimo.xiaomi.com/mimocode)
(Xiaomi, an OpenCode fork) as a [BenchFlow](https://github.com/benchflow-ai/benchflow) agent —
registered out-of-core via `register_agent`.

Unlike `harness-pi`/`-codex`/`-claude-code` (which wrap a vendor `@ai-sdk/harness-<x>` package
around a JS-library agent loop), **MiMo is itself a native ACP agent** (`mimo acp`). So the
HarnessAgent runs a **thin custom `HarnessV1` adapter** (`createMimo`) whose `doStart` spawns
`mimo acp` **on the host** (the harness sandbox's `SandboxProcess` has no writable stdin, which
ACP JSON-RPC needs) and bridges its `session/update` notifications into the AI SDK stream. No
vendor harness package, no JS-library wrap, no WebSocket bridge (~150-line adapter).

```
benchflow ──ACP/stdio──▶ server.mjs (HarnessAgent) ──ACP/stdio──▶ mimo acp (native)
```

## Usage tracking
Both modes work — the agent picks the route from `OPENAI_BASE_URL` at session start:

- **Proxy mode** (`usage_tracking="auto"`/`"required"`, the default): benchflow points
  `OPENAI_BASE_URL` at its LiteLLM usage proxy and passes the model as a `benchflow-*` alias.
  MiMo (an OpenCode fork) rejects an unknown alias via `models.dev` — *unless* it belongs to a
  **custom provider**. So `createMimoSession` writes a per-session `.mimocode/mimocode.json`
  registering an OpenAI-compatible provider `benchflow` pointed at the proxy, then sends the
  inner ACP `session/set_model` as `benchflow/<alias>`. MiMo POSTs to the proxy, which captures
  `trajectory/llm_trajectory.jsonl` (raw prompts/completions) and reports
  `usage_source=provider_response`. This is the path the merge-readiness eval exercises.
- **Usage-off mode** (`usage_tracking="off"`): no proxy is set, so MiMo gets the raw provider
  creds + the bare model id and usage is captured natively via the ACP `PromptResult.usage`.
  The free `mimo/mimo-auto` model needs no key.

```python
import ai_sdk_harness_mimo  # registers `ai-sdk-mimo` (aliases: ai-sdk-harness-mimo, mimo-harness)
from benchflow import SDK

# proxy mode (raw-LLM trajectory + provider_response usage)
await SDK().run(task_path="...", agent="ai-sdk-mimo", model="deepseek/deepseek-v4-flash")
# usage-off mode (free model, native ACP usage)
await SDK().run(task_path="...", agent="ai-sdk-mimo", model="mimo/mimo-auto", usage_tracking="off")
```

## How it works
- `register.py` registers `ai-sdk-mimo` (`protocol="acp"`, `api_protocol="openai-completions"`,
  `acp_model_format="bare"`); `install_cmd` installs `@ai-sdk/harness@1.0.0-canary.13`
  (exact canary pin — no stable release) + `@mimo-ai/cli@0.1.1` into an isolated node
  prefix; `launch_cmd` runs `node server.mjs`.
- `server.mjs` builds `new HarnessAgent({ harness: createMimo(...), sandbox: <host-fs> })`, maps
  the agent's `fullStream` → ACP `session/update`, and bridges task files ⇄ MiMo's per-session
  workdir (seed in / sync back) so the verifier sees outputs.

## Dev
```bash
uv venv --python 3.12 && . .venv/bin/activate
uv pip install benchflow pytest ruff && uv pip install -e . --no-deps
pytest -q && ruff check src tests && ruff format --check src tests
```

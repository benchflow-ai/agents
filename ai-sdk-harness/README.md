# ai-sdk-harness

The **[Vercel AI SDK 7 `HarnessAgent`](https://ai-sdk.dev/v7/providers/ai-sdk-harnesses)**
(running the **Pi** harness) as a [BenchFlow](https://github.com/benchflow-ai/benchflow)
agent over [ACP](https://github.com/zed-industries/agent-client-protocol).

> ⚠️ **Experimental / canary.** Built on `@ai-sdk/harness@canary` (AI SDK 7,
> pre-release). APIs and behavior may change. See caveats below.

A pure-JS ACP-over-stdio server (`server.mjs`) wraps `HarnessAgent` running the
Pi harness on the **local** `@ai-sdk/sandbox-just-bash` sandbox, so the harness
runs *inside* benchflow's task sandbox on the real task files. `register.py`
wires it in via the public `register_agent` extension point — sibling to
[`ai-sdk-acp`](../ai-sdk-acp) (which runs the AI SDK's own `ToolLoopAgent`).

## Why only the Pi harness

`HarnessAgent` ships three harnesses; only **Pi** runs natively in benchflow:

| Harness | Runs in benchflow? | Why |
|---|---|---|
| **Pi** | ✅ | In-process (no bridge); runs on the local just-bash sandbox |
| claude-code | ❌ | Bridge-backed — needs a port-exposing (Vercel) sandbox; just-bash rejects it. (benchflow runs Claude Code natively via `claude-agent-acp`.) |
| codex | ❌ | Same bridge requirement. (benchflow runs Codex natively via `codex-acp`.) |

## How it runs

- **Sandbox:** `Sandbox.create({ fs: new ReadWriteFs({ root: cwd, allowSymlinks: true }) })`
  backs just-bash with real disk so the agent operates on the task files.
- **FS bridge:** the harness composes a per-session working dir
  `<root>/pi-<sessionId>`, but the verifier checks the task cwd. So the server
  pre-seeds task files into the session dir, **syncs results back** to the task
  cwd (relative-path tasks), and **symlinks** `<cwd>/<basename> → <cwd>` so
  absolute `/app/...` paths resolve to the real task dir (absolute-path tasks).
- **Model:** Pi's `openai` slot uses the Responses API; Pi routes other models
  through its `openrouter` slot (chat-completions). `register.py` maps the
  provider base/key to `OPENROUTER_*` and sends the bare model id.

## ⚠️ Run with `usage_tracking="off"`

Pi mangles benchflow's LiteLLM-proxy model **alias** and falls back to its own
default model (→ proxy `400`). So bypass the proxy: Pi then gets the **raw**
provider creds + bare model id (the config that works). Token usage is still
captured — **natively** via `agent_native_acp` (Pi's `finish.totalUsage` →
ACP `PromptResult.usage`), so `result.json` reports real token counts.

```python
from ai_sdk_harness.register import register
register()  # adds "ai-sdk-harness" (aliases: ai-sdk-pi, pi-harness)

import asyncio
from benchflow.runtime import run, Agent, Environment, RuntimeConfig

async def main():
    env = Environment.from_task("path/to/task", sandbox="daytona")
    cfg = RuntimeConfig(usage_tracking="off")          # <-- required (see above)
    res = await run(Agent("ai-sdk-harness", "deepseek/deepseek-v4-flash"), env, cfg)
    print(res.rollout_dir)

asyncio.run(main())
```

## Verified

On Daytona with DeepSeek (`deepseek-v4-flash`):

| Task | reward | tool calls | usage |
|---|---|---|---|
| hello-world (relative path) | 1.0 | 2 (`write`, `fileChange`) | `agent_native_acp` |
| terminal-bench-smoke (exec script + nested file, absolute `/app` paths) | 1.0 | 15 (`ls`, `write`, `bash`×13) | `agent_native_acp` |

Inside-vs-outside parity: identical tool-use + file output + `end_turn` (token
counts vary only within model sampling non-determinism) — benchflow does not
perturb the harness.

## Caveats

- **Canary** packages — expect churn.
- **just-bash** is a JS reimplementation of bash with networking off by default.
  The model call is in-process (unaffected), but in-sandbox `pip`/`pytest`/real
  binaries are likely unsupported — file/shell tasks work; heavyweight
  repo+pytest workloads may hit just-bash's command limits.
- Usage is `agent_native_acp` (Pi self-reports), not gateway-captured, because
  Pi's model resolution requires bypassing the LiteLLM proxy.
- The sync-back is **additive**: files the agent *creates/edits* propagate to the
  task cwd, but files it *deletes/renames* are not removed from the cwd — tasks
  graded on "X removed" can get a false negative.
- If the task dir has a top-level entry named like its basename (e.g. an `app/`
  under cwd `/app`), the absolute-path symlink is skipped (no clobber) and
  absolute `/app/...` writes land in that subdir instead of the task root.

## Dev

```bash
cd ai-sdk-harness
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q                                        # key-free; no sandbox/model needed
ruff check src tests
```

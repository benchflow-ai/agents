# acp-registry

**The [Agent Client Protocol registry](https://agentclientprotocol.com/get-started/registry), mapped onto BenchFlow.**

The ACP registry is a fast-growing list of agents — Qwen Code, goose, Cline,
GitHub Copilot, Stakpak, and ~30 more — that all speak ACP over stdio. Because
BenchFlow drives agents over ACP, that registry is a natural source of agents to
benchmark. This package answers the practical question for **every** agent in it:
*can it run as a faithful, model-enforced BenchFlow eval — and if so, how?*

It is the same eval↔prod-gap story as the rest of this repo ([root README](../README.md)):
these agents ship in production (in Zed, JetBrains, a terminal); here the **same
binary** runs as an eval harness, with no reimplementation. What you benchmark is
what users run.

## What "adapting" an ACP agent means

Every registry agent is already an ACP server, so there's no server to write
(unlike [`ai-sdk/`](../ai-sdk)). Adapting one is a thin registration: install it,
launch it in ACP mode, and route its model calls through BenchFlow's gateway via
`env_mapping` so the **benchmark's** model is enforced and usage is captured.

Whether that routing is *possible* is the whole question — and it cleanly splits
the registry. The full classification of all 36 agents is in **[AGENTS.md](AGENTS.md)**
(generated from [`catalog.py`](src/acp_registry/catalog.py), the single source of
truth). The tiers:

| Tier | Meaning |
|---|---|
| 🟦 **native** | BenchFlow already ships a built-in (`claude-agent-acp`, `codex-acp`, `gemini`, `opencode`, `pi-acp`). Use it; we don't shadow it. |
| ✅ **wired** | Registered here, routes correctly **by construction** (confirmed env vars + a model format BenchFlow can emit). |
| 📋 **catalog** | BYO-provider — *adaptable*, but held back by something this npx-only first pass doesn't ship (a config-file writer, a binary installer, a uvx bootstrap, or a model-id format BenchFlow can't emit). Each carries the **exact recipe**. |
| 🔒 **vendor-locked** | Authenticates only to its vendor's backend — no arbitrary base URL. Can't enforce the benchmark's model, so it can't be a faithful eval. |
| ➖ **out-of-scope** | Not a single LLM coding/eval agent (e.g. an agent marketplace). |

The split is the contribution: most ACP agents are coding-vendor CLIs locked to
their own backend, so a smaller set is genuinely benchmarkable. We say which, and
why, with a source for each claim.

## Use it

```bash
pip install "acp-registry @ git+https://github.com/benchflow-ai/agents#subdirectory=acp-registry"
```

```python
import acp_registry
acp_registry.register()              # register all wired agents
# acp_registry.register("qwen-code") # …or a subset

from benchflow import SDK
await SDK().run(task_path="...", agent="qwen-code", model="deepseek/deepseek-chat")
```

Inspect the classification programmatically:

```python
from acp_registry import by_status, CATALOG
for a in by_status(CATALOG):
    print(a.registry_id, "→", a.reason)   # the recipe to wire it
```

## Wired agents

### [Qwen Code](https://github.com/QwenLM/qwen-code) (`qwen-code`)

The cleanest fit in the registry: base URL, key, **and** model are all plain env
vars (`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`), so BenchFlow's
`env_mapping` routes it with no config file and no model-id translation. It speaks
`openai-completions`, so any OpenAI-compatible provider the gateway exposes works.

#### Verification (and the BenchFlow gap it surfaced)

Running qwen-code end-to-end exposed a real, **general** integration gap — exactly
the kind a paper exercise would miss:

> qwen-code (a Gemini-CLI fork) **advertises an ACP `model` session config
> option**, and validates its value against its *own* model list. BenchFlow's
> capability-first dispatch sees that option and tries to set the benchmark's
> model id through it — which qwen-code rejects with ACP `-32603`, with **both**
> a gateway alias (`benchflow-deepseek-…`) **and** a bare `deepseek-v4-flash`.
> The agent never gets to run.

This isn't a qwen-code quirk — many ACP agents validate model ids against their
own catalogs, which don't contain benchmark/gateway ids. The model is *already*
delivered out-of-band via `OPENAI_MODEL`, so the fix is to **not** drive it over
ACP at all. That's a small, general BenchFlow change — an `acp_model_via_env`
registry flag that skips ACP model configuration entirely (proposed in this PR).
This package enables it via feature-detection; on a BenchFlow build without it,
`register()` warns and qwen-code fails at model configuration.

With that flag, qwen-code runs natively:

| Task | Sandbox | Model | Result |
|---|---|---|---|
| `hello-world` (toy sanity) | Daytona | `deepseek/deepseek-v4-flash` | ✅ **reward 1.0** — 1 tool call, file written, verifier passed |
| `skillsbench/citation-check` (real) | Daytona | `deepseek/deepseek-v4-flash` | ✅ **reward 1.0** — 33 tool calls, 68 steps, no errors |

The real task matters: `citation-check` ships an input file (`/root/test.bib`) and
a skill, and needs the agent to verify citations (web lookups, 33 tool calls) and
write `/root/answer.json`. It's the **same task `ai-sdk/harness-pi` couldn't do**
(its just-bash sandbox hides task files); qwen-code runs in a real Daytona sandbox,
so it sees the file and solves it. Full trajectory is in the PR comments.

## Adding more agents

The catalog is registry-driven: wiring a 📋 catalog agent is a one-spec change in
[`catalog.py`](src/acp_registry/catalog.py) (flip `status` to `wired`, fill the
profile) plus whatever the recipe calls for (a config-file writer for the
config-file ones, a binary/uvx install path for those distributions). The
[adaptation-parity skill](../skills/adaptation-parity) verifies the result behaves
the same inside BenchFlow as standalone.

To track the upstream registry:

```bash
python scripts/refresh_registry.py            # diff live registry vs our snapshot
python scripts/refresh_registry.py --write    # update the snapshot, then reconcile catalog.py
python scripts/gen_agents_md.py > AGENTS.md    # regenerate the table
```

## The honesty bar

> Consistent with the [repo's bar](../README.md): **wired** means "registers and
> routes correctly by construction," **not** "passes real workloads." Only agents
> with a recorded **verification** have been run end-to-end, and only on the exact
> tasks named. The 📋 catalog recipes come from each agent's upstream docs/source
> (cited per entry), not from a run — treat them as a tested-on-paper starting
> point, and verify before trusting.

## Dev

```bash
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q          # key-free; no sandbox/model needed
ruff check src tests scripts
```

## License

Apache-2.0 (see [LICENSE](LICENSE)). Each adapted agent keeps its own upstream
license — recorded per entry in [AGENTS.md](AGENTS.md).

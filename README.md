<div align="center">

# BenchFlow Agents

**Agents that run the same in evaluation and in production — closing the gap between the two.**

[![lint](https://github.com/benchflow-ai/agents/actions/workflows/lint.yaml/badge.svg)](https://github.com/benchflow-ai/agents/actions/workflows/lint.yaml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](#license)

[The eval ↔ prod gap](#the-eval--prod-gap) ·
[Agents](#agents-three-paths-into-benchflow) ·
[Tiers](#tiers-how-faithfully-can-we-host-it) ·
[Parity](#parity-the-same-agent-in-both) ·
[Adapt a new agent](#adapt--verify-a-new-agent) ·
[Contributing](#contributing)

</div>

---

## The eval ↔ prod gap

Most teams build an agent for **production** (a CLI, a TUI, an app) and then
*re-implement or approximate* it to **evaluate** it — a different harness, a
different scaffold, different tool plumbing. So the benchmark measures something
other than what ships, and the numbers don't transfer.

This repo's premise is the opposite: **one agent, used both ways.** Every agent
here runs in production (an interactive TUI, the Vercel AI SDK, a coding CLI)
*and* as an evaluation harness on [BenchFlow](https://github.com/benchflow-ai/benchflow)
over [ACP](https://agentclientprotocol.com) — with no reimplementation. What you
benchmark is what you ship. That's the gap we're closing.

And not just *coding* agents: mini-swe is a coding harness, but the Vercel AI SDK
agents are general, tool-using agent frameworks (build any agent), and BenchFlow
evaluations span well beyond code. The repo is a home for agents of any kind that
you want to both ship and benchmark.

## Agents: three paths into BenchFlow

Every agent reaches BenchFlow through one of **three paths**, by how it's wrapped —
each a top-level directory:

| Path | How an agent adapts | Agents in it | Eval on BenchFlow |
|---|---|---|---|
| [**`acp/`**](acp/) · ACP over stdio | a declarative [`acp/<id>/manifest.toml`](acp/) (registry CLIs that already speak ACP — no code), or a self-contained ACP package | the **[36-agent ACP registry](acp-registry/)** (goose, Qwen Code, Stakpak, GitHub Copilot, GLM, …) + [**mini-swe**](acp/mini-swe-code/) (SWE-agent behind opencode's TUI) + [**mimo**](acp/mimo-acp/) (Xiaomi MiMo Code, native `mimo acp`) | registry: **13 wired · 14 runnable · 6 native** ([tiers](#tiers-how-faithfully-can-we-host-it) · [AGENTS.md](acp-registry/AGENTS.md)); mini-swe ✅ stable (>74% SWE-bench verified); mimo ✅ free `mimo-auto` runs headless |
| [**`ai-sdk/`**](ai-sdk/) · Vercel AI SDK | a pure-JS `server.mjs` + `register.py` wrapping the AI SDK agent | `ToolLoopAgent` ([**acp**](ai-sdk/acp/)) and `HarnessAgent` × {[pi](ai-sdk/harness-pi/), [codex](ai-sdk/harness-codex/), [claude-code](ai-sdk/harness-claude-code/), [mimo](ai-sdk/harness-mimo/)} | `acp` ✅ parity byte-verified · `harness-pi` ✅ (file tasks) · `codex`/`claude-code` 🧪 (need a Vercel sandbox) — [ai-sdk/README](ai-sdk/README.md) |
| [**`omnigent/`**](omnigent/) · non-ACP Session | a `session_factory` that shells `omnigent run` inside the sandbox | [Databricks Omnigent](https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents) `pi` meta-harness — the **only non-ACP** agent here | ✅ reward 1.0 on hello-world **and** the real `citation-check` task (DeepSeek/Daytona x86_64); needs the session-factory seam — [omnigent/README](omnigent/README.md) |

Within those paths an agent takes one of **two shapes**: a few **self-contained
packages** (the `mini-swe-*` runtimes, the `ai-sdk/*` group, `omnigent`) — a
production runtime + a thin adapter registered via the public `register_agent`
extension point — or a **declarative [`acp/<id>/manifest.toml`](acp/) agent** for an
ACP-registry CLI that already speaks ACP (no adapter code; discovered via the
manifest loader, classified by tier in [acp-registry](acp-registry/)).

## Tiers: how faithfully can we host it?

Not every agent can be benchmarked the same way. We classify each by *how much of a
run BenchFlow captures* — the bar for adaptation is the floor (**BenchFlow can create
the experiment and track the run's logs**); the tier says how much is captured above
it. Full reference in [docs/tiers.md](docs/tiers.md); live per-agent table in
[acp-registry/AGENTS.md](acp-registry/AGENTS.md).

| Tier | What BenchFlow tracks |
|---|---|
| ✅ **wired** + 🟦 **native** | raw-LLM trajectory (gateway proxy) **and** ACP-trajectory logs — model-enforced, wire-parity-verifiable |
| 🏃 **runnable** | ACP-trajectory logs **only** — the model runs on the agent's own/vendor backend, not gateway-enforced (executable, not a faithful model-enforced eval) |
| 📋 **catalog** / 🔒 **vendor-locked** / ➖ **out-of-scope** | not adapted — a wiring to-do (recipe or block recorded), a backend-locked CLI, or a non-single-model agent |

Snapshot `v1.0.0`: **wired 13 · runnable 14 · catalog 1 · native 6 · vendor-locked 1
· out-of-scope 1** (36 total) — [AGENTS.md](acp-registry/AGENTS.md) is authoritative.

## Parity: the same agent in both

The point isn't just "it runs in both places" — it's that it **behaves the same**
in both. For `ai-sdk/acp` this is verified at the wire level: driven inside
BenchFlow vs. standalone, the upstream model request is **byte-identical** (same
system+user prompt, tools, sampling params) apart from neutral gateway artifacts;
tool-use, file output, reward, and finish reason match. BenchFlow provides the
environment and captures the trajectory — it does not perturb the agent. The
[**adaptation-parity skill**](skills/adaptation-parity) automates this check;
methodology in [docs/parity.md](docs/parity.md).

Wire parity is the bar for the **wired** and **native** [tiers](#tiers-how-faithfully-can-we-host-it)
(the model is proxied through BenchFlow's gateway, so there's a request to byte-diff);
**runnable** agents run the model on their own backend, so they're held to outcome
parity only.

> **Honesty matters more than a green checkmark.** Toy tasks (a single file write)
> pass easily and prove little; real eval workloads — input files, real toolchains
> (`pytest`, network), skills — expose the gaps. No agent here is "verified" beyond
> its quickstart; e.g. `harness-pi` passes hello-world but not the real SkillsBench
> `citation-check`. We need **more tasks, of more variants**, run end-to-end. Each
> package README states plainly what it has and hasn't been run against.

## Adapt & verify a new agent

The bar is **BenchFlow can create the experiment and track the run's logs**; how much
it captures sets the [tier](#tiers-how-faithfully-can-we-host-it). Two routes:

1. **Already speaks ACP** (most registry CLIs) — add a declarative
   [`acp/<id>/manifest.toml`](acp/) and classify it in
   [`acp-registry`](acp-registry/src/acp_registry/catalog.py); no adapter code. The
   `contract/` tests validate the manifest. ([docs/adaptation.md](docs/adaptation.md))
2. **Needs an adapter** (a TUI, an SDK agent, a non-ACP harness) — write an ACP
   server + `register.py`. Scaffold from `ai-sdk/acp`:
   `python skills/adaptation-parity/scripts/scaffold_ai_sdk_agent.py <name>`.

Then **verify parity** — inside vs. standalone, with the skill's `acp_capture.mjs` +
`parity_diff.py` (wired/native; [docs/parity.md](docs/parity.md)).

## Quickstarts

**Drive an agent interactively (mini-swe-code):**

```bash
cd acp/mini-swe-code
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[opencode]"
export ANTHROPIC_API_KEY="<your-key>"   # or OPENAI_API_KEY / GEMINI_API_KEY / ...
mkdir -p /tmp/mini-swe-scratch
mini-opencode --attach --cwd /tmp/mini-swe-scratch
```

> [!NOTE]
> The agent executes commands **locally without confirmation** inside `--cwd` —
> point it at a scratch directory.

**Benchmark an agent (mini-swe-acp):**

```bash
pip install "mini-swe-acp @ git+https://github.com/benchflow-ai/agents#subdirectory=acp/mini-swe-acp"
```

```python
import mini_swe_acp  # registers "mini-swe" (aliases: mini, minisweagent, mini-swe-agent)
from benchflow import SDK
await SDK().run(task_path="...", agent="mini-swe", model="openai/gpt-4o-mini")
```

Per-agent setup, design notes, and caveats live in each package's README:
[mini-swe-code](acp/mini-swe-code/README.md) ·
[mini-swe-acp](acp/mini-swe-acp/README.md) ·
[ai-sdk/*](ai-sdk/README.md). For the ACP-registry agents, the generated
[acp-registry/AGENTS.md](acp-registry/AGENTS.md) lists every agent's tier, wiring
recipe, and known issues.

## Repository layout

```text
acp/              all ACP agents — 2 self-contained packages + 38 declarative manifests:
  mini-swe-code/      mini-swe-agent distribution + opencode TUI (CLIs: mini, mini-opencode)
  mini-swe-acp/       mini-swe-agent as a BenchFlow ACP agent
  <id>/manifest.toml  declarative registry agents (goose, qwen-code, …) + shims (mimo, …), no server code
acp-registry/     classifies the 36 ACP-registry agents into 6 tiers (catalog.py → AGENTS.md)
ai-sdk/           Vercel AI SDK agents: acp, harness-pi, harness-codex, harness-claude-code, harness-mimo
omnigent/         Databricks Omnigent pi meta-harness as a non-ACP (session-factory) BenchFlow agent
contract/         versioned manifest schema + loader + contract tests (validates acp/<id>/manifest.toml)
skills/           adaptation-parity skill — adapt an agent + verify eval/prod parity
docs/             adaptation.md, parity.md, tiers.md, CONTEXT.md, adr/ (0001–0003)
.github/          CI: per-family tests (path-filtered), ruff lint, markdown link check
```

Add an agent either way: a declarative `acp/<id>/manifest.toml` + a
[`catalog.py`](acp-registry/src/acp_registry/catalog.py) tier entry (validated by the
`contract/` tests), or a self-contained package + a per-package CI workflow (or extend
the `ai-sdk` matrix). Each package still builds, tests, and ships independently.

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). High-value now:

- **More benchmark tasks, of more variants** — input-file / real-toolchain
  (`pytest`/build) / skill-based — run end-to-end against each agent to find and
  close eval↔prod behavior gaps.
- New agent integrations (any production agent + a thin ACP adapter; scaffold +
  verify with the [adaptation-parity skill](skills/adaptation-parity)).
- Parity reports: same agent, inside-BenchFlow vs. standalone, audited.

## License

| Path | License |
|---|---|
| repository root, `acp/mini-swe-acp/`, `acp-registry/`, `ai-sdk/`, `omnigent/`, `contract/`, `skills/` | [Apache-2.0](LICENSE) |
| `acp/mini-swe-code/` | [MIT](acp/mini-swe-code/LICENSE.md) (upstream mini-swe-agent license, kept verbatim) |
| `acp/<id>/` manifest agents | each keeps its upstream license — recorded per entry in [acp-registry/AGENTS.md](acp-registry/AGENTS.md) |

## Acknowledgments

- [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) and the
  SWE-bench / SWE-agent team. If useful in research, cite their
  [SWE-agent paper](https://arxiv.org/abs/2405.15793).
- [Vercel AI SDK](https://ai-sdk.dev) — the toolkit behind the `ai-sdk` agents.
- [opencode](https://opencode.ai) — the TUI that makes the agent a pleasure to drive.
- [Agent Client Protocol](https://agentclientprotocol.com) — the editor/agent-agnostic protocol the eval shims speak.
- [ACP registry](https://agentclientprotocol.com/get-started/registry) — the source of the 36 ACP agents the [`acp-registry`](acp-registry/) package maps onto BenchFlow.

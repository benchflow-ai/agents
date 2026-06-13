<div align="center">

# BenchFlow Agents

**Agents that run the same in evaluation and in production — closing the gap between the two.**

[![lint](https://github.com/benchflow-ai/agents/actions/workflows/lint.yaml/badge.svg)](https://github.com/benchflow-ai/agents/actions/workflows/lint.yaml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](#license)

[The eval ↔ prod gap](#the-eval--prod-gap) ·
[Agents](#agents) ·
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

## Agents

| Family | Agents | Eval on BenchFlow |
|---|---|---|
| [**mini-swe**](mini-swe-code/) | [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) behind opencode's TUI ([mini-swe-code](mini-swe-code/)) + an ACP shim ([mini-swe-acp](mini-swe-acp/)) | ✅ stable — faithful SWE-agent harness (>74% SWE-bench verified) |
| [**ai-sdk**](ai-sdk/) | the Vercel AI SDK agent surface — `ToolLoopAgent` ([acp](ai-sdk/acp/)) and `HarnessAgent` × {[pi](ai-sdk/harness-pi/), [codex](ai-sdk/harness-codex/), [claude-code](ai-sdk/harness-claude-code/)} | mixed — `acp` ✅ (parity byte-verified), `harness-pi` ✅ (file tasks), `codex`/`claude-code` 🧪 (need a Vercel sandbox). Per-agent maturity in [ai-sdk/README](ai-sdk/README.md). |

Each agent is a self-contained package: a production runtime + a thin ACP adapter
registered via the public `register_agent` extension point.

## Parity: the same agent in both

The point isn't just "it runs in both places" — it's that it **behaves the same**
in both. For `ai-sdk/acp` this is verified at the wire level: driven inside
BenchFlow vs. standalone, the upstream model request is **byte-identical** (same
system+user prompt, tools, sampling params) apart from neutral gateway artifacts;
tool-use, file output, reward, and finish reason match. BenchFlow provides the
environment and captures the trajectory — it does not perturb the agent. The
[**adaptation-parity skill**](skills/adaptation-parity) automates this check;
methodology in [docs/parity.md](docs/parity.md).

> **Honesty matters more than a green checkmark.** Toy tasks (a single file write)
> pass easily and prove little; real eval workloads — input files, real toolchains
> (`pytest`, network), skills — expose the gaps. No agent here is "verified" beyond
> its quickstart; e.g. `harness-pi` passes hello-world but not the real SkillsBench
> `citation-check`. We need **more tasks, of more variants**, run end-to-end. Each
> package README states plainly what it has and hasn't been run against.

## Adapt & verify a new agent

1. **Adapt** — write an ACP server + `register.py` ([docs/adaptation.md](docs/adaptation.md)).
   Scaffold from `ai-sdk/acp`:
   `python skills/adaptation-parity/scripts/scaffold_ai_sdk_agent.py <name>`.
2. **Verify parity** — inside vs. standalone, with the skill's `acp_capture.mjs` +
   `parity_diff.py` ([docs/parity.md](docs/parity.md)).

## Quickstarts

**Drive an agent interactively (mini-swe-code):**

```bash
cd mini-swe-code
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
pip install "mini-swe-acp @ git+https://github.com/benchflow-ai/agents#subdirectory=mini-swe-acp"
```

```python
import mini_swe_acp  # registers "mini-swe" (aliases: mini, minisweagent, mini-swe-agent)
from benchflow import SDK
await SDK().run(task_path="...", agent="mini-swe", model="openai/gpt-4o-mini")
```

Per-agent setup, design notes, and caveats live in each package's README:
[mini-swe-code](mini-swe-code/README.md) ·
[mini-swe-acp](mini-swe-acp/README.md) ·
[ai-sdk/*](ai-sdk/README.md).

## Repository layout

```text
mini-swe-code/    mini-swe-agent distribution + opencode TUI (CLIs: mini, mini-opencode)
mini-swe-acp/     mini-swe-agent as a BenchFlow ACP agent
ai-sdk/           Vercel AI SDK agents: acp, harness-pi, harness-codex, harness-claude-code
skills/           adaptation-parity skill — adapt an agent + verify eval/prod parity
docs/             adaptation.md, parity.md
.github/          CI: per-family tests (path-filtered), ruff lint, markdown link check
```

Each package builds, tests, and ships independently; add a new agent as a new
package + a per-package CI workflow (or extend the `ai-sdk` matrix).

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
| repository root, `mini-swe-acp/`, `ai-sdk/`, `skills/` | [Apache-2.0](LICENSE) |
| `mini-swe-code/` | [MIT](mini-swe-code/LICENSE.md) (upstream mini-swe-agent license, kept verbatim) |

## Acknowledgments

- [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) and the
  SWE-bench / SWE-agent team. If useful in research, cite their
  [SWE-agent paper](https://arxiv.org/abs/2405.15793).
- [Vercel AI SDK](https://ai-sdk.dev) — the toolkit behind the `ai-sdk` agents.
- [opencode](https://opencode.ai) — the TUI that makes the agent a pleasure to drive.
- [Agent Client Protocol](https://agentclientprotocol.com) — the editor/agent-agnostic protocol the eval shims speak.

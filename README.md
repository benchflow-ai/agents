<div align="center">

# BenchFlow Agents

**Minimal coding agents — easy to play with, easy to benchmark.**

[![mini-swe-acp](https://github.com/benchflow-ai/agents/actions/workflows/test-mini-swe-acp.yaml/badge.svg)](https://github.com/benchflow-ai/agents/actions/workflows/test-mini-swe-acp.yaml)
[![mini-swe-code](https://github.com/benchflow-ai/agents/actions/workflows/test-mini-swe-code.yaml/badge.svg)](https://github.com/benchflow-ai/agents/actions/workflows/test-mini-swe-code.yaml)
[![lint](https://github.com/benchflow-ai/agents/actions/workflows/lint.yaml/badge.svg)](https://github.com/benchflow-ai/agents/actions/workflows/lint.yaml)
[![License](https://img.shields.io/badge/license-Apache--2.0%20%2B%20MIT-blue)](#license)

[Play with it](#-play-with-it--mini-swe-code) ·
[Benchmark with it](#-benchmark-with-it--mini-swe-acp) ·
[How it works](#how-it-works) ·
[Contributing](#contributing)

</div>

---

[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) is the ~100-line
coding agent from the SWE-bench team: **one bash tool, one shared system
prompt, no vendor editing primitives**. Because the scaffold is identical for
every model, it's become the go-to harness for apples-to-apples model
comparisons (it scores >74% on SWE-bench verified, and recent benchmarks built
on it report it matching or beating the vendors' own harnesses).

We were impressed — so this repo packages it two ways:

| Package | What it is | Use it for |
|---|---|---|
| 🖥️ [**mini-swe-code**](mini-swe-code/) | mini-swe-agent behind [opencode](https://opencode.ai)'s terminal UI, with the TUI binary bundled (`mini-opencode`) | Driving the agent interactively, like any modern coding CLI |
| 📊 [**mini-swe-acp**](mini-swe-acp/) | mini-swe-agent as a [BenchFlow](https://github.com/benchflow-ai/benchflow) agent speaking [ACP](https://agentclientprotocol.com) | Running it as the evaluation harness on any BenchFlow benchmark |

Same agent core in both — what you play with is exactly what gets benchmarked.

## 🖥️ Play with it — mini-swe-code

```bash
git clone https://github.com/benchflow-ai/agents.git
cd agents/mini-swe-code

uv venv .venv && source .venv/bin/activate
uv pip install -e ".[opencode]"

export ANTHROPIC_API_KEY="<your-key>"   # or OPENAI_API_KEY / GEMINI_API_KEY / ...
mkdir -p /tmp/mini-swe-scratch
mini-opencode --attach --cwd /tmp/mini-swe-scratch
```

This opens opencode's real TUI in your terminal: pick a model, type a task, and
the agent's bash steps render as native tool calls. Self-contained — no `bun`,
no opencode checkout (a prebuilt TUI binary ships in the package; macOS arm64
today, [rebuild instructions](mini-swe-code/docs/usage/opencode_tui.md) for
other platforms).

> [!NOTE]
> The agent executes commands **locally without confirmation** inside `--cwd`,
> so point it at a scratch directory.

Step-by-step setup, an end-to-end smoke test, and troubleshooting:
[mini-swe-code/README.md](mini-swe-code/README.md).

## 📊 Benchmark with it — mini-swe-acp

```bash
pip install "mini-swe-acp @ git+https://github.com/benchflow-ai/agents#subdirectory=mini-swe-acp"
```

```python
import mini_swe_acp  # registers "mini-swe" (aliases: mini, minisweagent, mini-swe-agent)

from benchflow import SDK
await SDK().run(task_path="...", agent="mini-swe", model="openai/gpt-4o-mini")
```

What you get:

- **Faithful harness** — runs mini-swe's own `DefaultAgent` loop with the
  upstream `mini.yaml` guardrails reproduced verbatim: single bash tool, shared
  system/instance templates, >10k-char output truncation, malformed tool calls
  caught and retried with guidance.
- **Full trajectories** — every step re-emitted as ACP `session/update`
  notifications, captured by BenchFlow.
- **Provider routing built in** — reads `BENCHFLOW_PROVIDER_*`, so the usage
  proxy and providers (incl. AWS Bedrock, Azure Foundry) work like built-in
  agents.

Details and design notes: [mini-swe-acp/README.md](mini-swe-acp/README.md).

## How it works

```text
   interactive use                          benchmarking
┌────────────────────────┐         ┌────────────────────────────┐
│ opencode TUI (bundled) │         │ BenchFlow (any benchmark)  │
└───────────┬────────────┘         └──────────────┬─────────────┘
            │ HTTP + SSE                          │ ACP over stdio
┌───────────▼────────────┐         ┌──────────────▼─────────────┐
│ mini-opencode server   │         │ acp_shim.py                │
│ (mini-swe-code)        │         │ (mini-swe-acp)             │
└───────────┬────────────┘         └──────────────┬─────────────┘
            │ in-process                          │ in-process
            └─────────────────┬───────────────────┘
                  ┌───────────▼────────────┐
                  │ mini-swe-agent         │
                  │ DefaultAgent loop      │
                  │ (one bash tool,        │
                  │  subprocess.run)       │
                  └────────────────────────┘
```

Both packages embed the agent in-process and translate its steps into a
protocol: the opencode wire protocol for the TUI, ACP for BenchFlow. The agent
core is untouched.

## Repository layout

```text
mini-swe-acp/    BenchFlow ACP integration (Python package: mini_swe_acp)
mini-swe-code/   mini-swe-agent v2.3.0 distribution + opencode TUI
                 (Python package: minisweagent; CLIs: mini, mini-extra, mini-opencode)
.github/         CI: per-package tests, ruff lint, markdown link check
```

## Contributing

Issues and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup,
test commands, and conventions. Good first contributions: a Linux/x86 TUI
binary build, more BenchFlow agent integrations, harness × model run reports.

## License

| Path | License |
|---|---|
| repository root, `mini-swe-acp/` | [Apache-2.0](LICENSE) |
| `mini-swe-code/` | [MIT](mini-swe-code/LICENSE.md) (upstream mini-swe-agent license, kept verbatim) |

## Acknowledgments

- [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) and the
  SWE-bench / SWE-agent team — the agent this repo is built around. If this
  work is useful in research, cite their
  [SWE-agent paper](https://arxiv.org/abs/2405.15793).
- [opencode](https://opencode.ai) — the TUI that makes the agent a pleasure to
  drive.
- [Agent Client Protocol](https://agentclientprotocol.com) — the
  editor/agent-agnostic protocol the eval shim speaks.

# ai-sdk

[Vercel AI SDK](https://ai-sdk.dev) agents as BenchFlow agents — the full AI SDK
agent surface, each runs in production *and* (where the sandbox allows) as a
BenchFlow eval harness over ACP. See the repo root for the eval↔prod-gap thesis,
and [`skills/adaptation-parity`](../skills/adaptation-parity) for the skill that
adapts + parity-checks them. ai-sdk is just one agent family — see
[`../acp-registry/AGENTS.md`](../acp-registry/AGENTS.md) for the full registry
across families.

> **Official source.** The harness adapters are published from the
> [vercel/ai monorepo](https://github.com/vercel/ai/tree/main/packages) as
> `packages/harness-*`: `harness-pi`, `harness-codex`, `harness-claude-code`,
> `harness-deepagents`, `harness-opencode`. This repo wraps **all five**. The base
> [`@ai-sdk/harness`](https://www.npmjs.com/package/@ai-sdk/harness)
> is the `HarnessAgent` abstraction itself, and `@ai-sdk/workflow-harness` runs a
> `HarnessAgent` as a durable workflow — neither is a registerable coding agent, so
> neither is listed here.

| Package | AI SDK abstraction | Runs in BenchFlow? |
|---|---|---|
| [**acp**](acp/) | `ToolLoopAgent` (you program the loop) | ✅ yes — gateway-routed; **inside==outside parity byte-verified** |
| [**harness-pi**](harness-pi/) | `HarnessAgent` + Pi harness | ✅ yes — in-process on the local just-bash sandbox; self-contained file tasks (not real toolchain workloads yet) |
| [**harness-codex**](harness-codex/) | `HarnessAgent` + Codex harness | ❌ no — bridge-backed, needs a Vercel sandbox (use native `codex-acp`). Template / completeness. |
| [**harness-claude-code**](harness-claude-code/) | `HarnessAgent` + Claude Code harness | ❌ no — bridge-backed, needs a Vercel sandbox (use native `claude-agent-acp`). Template / completeness. |
| [**harness-deepagents**](harness-deepagents/) | `HarnessAgent` + DeepAgents harness | 🧪 scaffolded — wraps `@ai-sdk/harness-deepagents`; in-process (just-bash) like Pi. Model routing + parity **not yet verified** (next step). |
| [**harness-opencode**](harness-opencode/) | `HarnessAgent` + OpenCode harness | 🧪 scaffolded — wraps `@ai-sdk/harness-opencode`; execution model (in-process vs bridge) + routing **not yet verified** (next step). |

The column is shorthand, not a tier — see [`../docs/tiers.md`](../docs/tiers.md)
for the tier model + per-tier log semantics, and [`../acp-registry/AGENTS.md`](../acp-registry/AGENTS.md)
for the live per-agent table. `acp` maps to the `wired` tier: gateway-routed by
construction, tracking the raw-LLM trajectory (proxy) + ACP-trajectory logs.

**Why the split**: the `HarnessAgent` harnesses divide by sandbox model. **Pi** is
in-process and runs on the local [`@ai-sdk/sandbox-just-bash`](https://www.npmjs.com/package/@ai-sdk/sandbox-just-bash)
sandbox, so it runs inside BenchFlow's task sandbox. **Codex** and **Claude Code**
are bridge-backed — they need a port-exposing Vercel sandbox, which is remote, so
their files don't reach BenchFlow's task `/app`; BenchFlow already runs both
natively via `codex-acp` / `claude-agent-acp`. Their adapters here are honest
templates, not working evals.

All packages above share the adapter pattern: a pure-JS ACP-over-stdio `server.mjs`
wrapping the AI SDK agent, registered via `register.py` (public `register_agent`),
atop `ai@6`. The vendor `@ai-sdk/harness*` packages span Vercel's AI SDK 7 line:
`harness-pi`/`-codex`/`-claude-code` install `@canary`, while the newer
`harness-deepagents`/`-opencode` pin the **stable** `@1.0.5`/`@1.0.6`.

New AI SDK agent? Scaffold from `acp`:
`python ../skills/adaptation-parity/scripts/scaffold_ai_sdk_agent.py <name>`.

# ai-sdk

[Vercel AI SDK](https://ai-sdk.dev) agents as BenchFlow agents — the full AI SDK
agent surface, each runnable in production *and* (where the sandbox allows) as a
BenchFlow eval harness over ACP. See the repo root for the eval↔prod-gap thesis,
and [`skills/adaptation-parity`](../skills/adaptation-parity) for the skill that
adapts + parity-checks them.

| Package | AI SDK abstraction | Runs natively in BenchFlow? |
|---|---|---|
| [**acp**](acp/) | `ToolLoopAgent` (you program the loop) | ✅ yes — gateway-routed; **inside==outside parity byte-verified** |
| [**harness-pi**](harness-pi/) | `HarnessAgent` + Pi harness | ✅ yes — in-process on the local just-bash sandbox; self-contained file tasks (not real toolchain workloads yet) |
| [**harness-codex**](harness-codex/) | `HarnessAgent` + Codex harness | ❌ no — bridge-backed, needs a Vercel sandbox (use native `codex-acp`). Template / completeness. |
| [**harness-claude-code**](harness-claude-code/) | `HarnessAgent` + Claude Code harness | ❌ no — bridge-backed, needs a Vercel sandbox (use native `claude-agent-acp`). Template / completeness. |

**Why the split**: the `HarnessAgent` harnesses divide by sandbox model. **Pi** is
in-process and runs on the local [`@ai-sdk/sandbox-just-bash`](https://www.npmjs.com/package/@ai-sdk/sandbox-just-bash)
sandbox, so it runs inside BenchFlow's task sandbox. **Codex** and **Claude Code**
are bridge-backed — they need a port-exposing Vercel sandbox, which is remote, so
their files don't reach BenchFlow's task `/app`; BenchFlow already runs both
natively via `codex-acp` / `claude-agent-acp`. Their adapters here are honest
templates, not working evals.

All four share the adapter pattern: a pure-JS ACP-over-stdio `server.mjs` wrapping
the AI SDK agent, registered via `register.py` (public `register_agent`). The
`@ai-sdk/harness*` packages are **canary** (AI SDK 7, pre-release).

New AI SDK agent? Scaffold from `acp`:
`python ../skills/adaptation-parity/scripts/scaffold_ai_sdk_agent.py <name>`.

## harness-mimo (MiMo Code)

`HarnessAgent` driving MiMo's **native** `mimo acp` via a thin custom `HarnessV1` adapter (no vendor `@ai-sdk/harness-<x>`, no JS-library wrap). Runs in-sandbox with the FS bridge, so it reads task input files AND writes outputs to the task cwd. Run `usage_tracking="off"`; free `mimo/mimo-auto` needs no key. See [harness-mimo/](harness-mimo/).

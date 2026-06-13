---
name: adaptation-parity
description: Adapt an agent to run on BenchFlow (ACP) and verify it behaves identically inside the eval harness vs standalone — closing the eval↔prod gap. Use when adding a new agent to this repo or checking an existing one for eval/prod behavior parity.
---

# Adaptation + Parity

This repo's thesis: **the agent you ship is the agent you benchmark.** This skill
makes that real in two steps — *adapt* an agent to BenchFlow, then *verify parity*
(it behaves the same inside the eval harness as standalone).

## 1. Adapt (agent → BenchFlow ACP)

An agent becomes a BenchFlow agent by speaking **ACP over stdio** and registering
via the public `register_agent` extension point. Pattern (see `ai-sdk/acp`,
`ai-sdk/harness-pi` for worked examples):

- **`server.mjs`** — a pure-JS ACP-over-stdio server. Newline-delimited JSON-RPC;
  **stdout = protocol only** (logs → stderr). Handle `initialize`, `session/new`,
  `session/set_model`, `session/prompt` (run the agent loop, stream
  `session/update` events, return `{stopReason, usage}`), `session/cancel`.
  Map the agent's stream → ACP: text→`agent_message_chunk`,
  reasoning→`agent_thought_chunk`, tool call→`tool_call` (name+args in `title`),
  tool result→`tool_call_update`. Route the model at `OPENAI_BASE_URL` (the gateway).
- **`register.py`** — `register_agent(name, install_cmd, launch_cmd, protocol="acp",
  api_protocol="openai-completions", env_mapping={BENCHFLOW_PROVIDER_*→agent vars},
  acp_model_format="bare", requires_env=[])`. `install_cmd` bootstraps node,
  base64-deploys `server.mjs`, and npm-installs deps in the sandbox.

For **prod parity**, the same `server.mjs`/loop must be the production runtime —
no eval-only reimplementation. That's the whole point.

Scaffold a new adapter: `python scripts/scaffold_ai_sdk_agent.py <name>` (prints a
ready-to-edit package skeleton mirroring `ai-sdk/acp`).

## 2. Verify parity (inside == outside)

Behavioral parity = given the same model responses, the agent sends the **same
request** and takes the **same actions** whether driven inside BenchFlow or
standalone. Verify at two levels:

**(a) Wire parity** — drive the agent's ACP server against a capturing mock
upstream, twice: standalone, and through BenchFlow's gateway. Diff the upstream
requests.

```bash
# standalone capture (drive the agent's server directly at the mock):
node scripts/acp_capture.mjs --server <path/to/server.mjs> --out /tmp/outside.jsonl
# inside-benchflow capture: run the registered agent on the same task with the
# gateway pointed at the same mock (see scripts/README), capturing /tmp/inside.jsonl
python scripts/parity_diff.py /tmp/outside.jsonl /tmp/inside.jsonl
```

`parity_diff.py` normalizes the **expected-neutral** differences (gateway
model-alias rename; sandbox cwd vs local; `content:null` vs omitted from proxy
re-aggregation) and reports any remaining diff in a field the model conditions on
(messages / tools / sampling params). PASS = byte-identical after normalization.

**(b) Outcome parity** — run the same task inside BenchFlow and standalone;
compare reward, tool sequence, and files produced. Token counts will differ
within model sampling non-determinism — that is *not* a divergence.

## The honesty bar

Toy tasks (a single file write) pass trivially and prove almost nothing. **Real
eval workloads — input files, real toolchains (`pytest`, network), skills — are
what expose gaps.** Do not call an agent "parity-verified" beyond the exact task
you ran it on. Run **many tasks, of more variants**, end-to-end (real SkillsBench
tasks, not synthetic toys), before claiming coverage. Record what you ran and
what failed, plainly. See `docs/parity.md`.

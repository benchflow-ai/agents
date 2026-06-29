# omnigent

[Databricks Omnigent](https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents)
as a [BenchFlow](https://github.com/benchflow-ai/benchflow) agent — the Omnigent
meta-harness wired in through the public `benchflow.register_agent` extension
point, maintained outside the core framework. The package lists **one BenchFlow
agent per Omnigent `--harness`** (see [Harnesses](#harnesses)); only
`omnigent-pi` is fully worked today, the rest are listed-not-wired (honest
status below).

Unlike the other agents in this repo, Omnigent does **not** speak ACP. It rides
BenchFlow's non-ACP **Session** path: the kernel resolves a per-harness
`session_factory` entrypoint and drives one `omnigent run --harness <value>` turn
per prompt, executed **inside the sandbox** via `Sandbox.exec`. ACP is the
*first* concrete `Session` implementation; this is a *second*.

```text
benchflow kernel ──session-factory──▶ OmnigentAgent.connect()         (host, in-process)
                                         └─ writes ~/.omnigent/config.yaml into sandbox
                 ──prompt(text)───────▶ OmnigentSession.prompt()       (host, in-process)
                                         └─ sandbox.exec: `omnigent run --harness <value> -p …`
                                                              └─ omnigent server + harness runner
                                                                   └─ writes files in /app
```

## Harnesses

One BenchFlow agent is registered per **canonical Omnigent harness**, named
`omnigent-<slug>` and wired to `omnigent run --harness <value>`. The set is the
**full** upstream list — derived from the source of truth
([`omnigent/inner/*_harness.py`](https://github.com/omnigent-ai/omnigent/tree/main/omnigent/inner)
+ `harness_aliases.py`), **not** the shorter README example: **22 harnesses**, of
which only `omnigent-pi` is fully worked today.

**Vendor SDK / CLI harnesses** (drive the vendor's own agent; each needs its CLI/SDK in-sandbox):

| BenchFlow agent | `--harness` value | status |
| --- | --- | --- |
| `omnigent-pi` | `pi` | **fully worked** — verified end-to-end (reward 1.0); `pi` CLI installed + model routing live |
| `omnigent-claude` | `claude-sdk` | listed — needs the Claude Code SDK (`@anthropic-ai/claude-agent-sdk`) (NEXT step) |
| `omnigent-codex` | `codex` | listed — needs the Codex SDK (`@openai/codex-sdk`) (NEXT step) |
| `omnigent-cursor` | `cursor` | listed — needs the cursor CLI (NEXT step) |
| `omnigent-opencode` | `opencode-native` | listed — needs the opencode binary (canonical `opencode-native`; `opencode` is its alias) (NEXT step) |
| `omnigent-hermes` | `hermes` | listed — needs the hermes CLI (NEXT step) |
| `omnigent-openai-agents` | `openai-agents` | listed — needs the OpenAI Agents SDK / python (NEXT step) |
| `omnigent-goose` | `goose` | listed — needs the goose binary (block/goose) (NEXT step) |
| `omnigent-qwen` | `qwen` | listed — needs the Qwen Code CLI (NEXT step) |
| `omnigent-kimi` | `kimi` | listed — needs the Kimi CLI (NEXT step) |
| `omnigent-copilot` | `copilot` | listed — needs the GitHub Copilot CLI (NEXT step) |
| `omnigent-antigravity` | `antigravity` | listed — needs Google Antigravity (NEXT step) |

**omnigent native drivers** (omnigent runs the agent directly, no vendor SDK):

| BenchFlow agent | `--harness` value | status |
| --- | --- | --- |
| `omnigent-pi-native` | `pi-native` | listed — omnigent native pi driver (NEXT step) |
| `omnigent-claude-native` | `claude-native` | listed — omnigent native Claude driver (NEXT step) |
| `omnigent-codex-native` | `codex-native` | listed — omnigent native Codex driver (NEXT step) |
| `omnigent-cursor-native` | `cursor-native` | listed — omnigent native Cursor driver (NEXT step) |
| `omnigent-hermes-native` | `hermes-native` | listed — omnigent native Hermes driver (NEXT step) |
| `omnigent-goose-native` | `goose-native` | listed — omnigent native goose driver (NEXT step) |
| `omnigent-qwen-native` | `qwen-native` | listed — omnigent native Qwen driver (NEXT step) |
| `omnigent-kimi-native` | `kimi-native` | listed — omnigent native Kimi driver (NEXT step) |
| `omnigent-antigravity-native` | `antigravity-native` | listed — omnigent native Antigravity driver (NEXT step) |
| `omnigent-kiro-native` | `kiro-native` | listed — Kiro (native-only harness) (NEXT step) |

**Listed-not-wired** means: the agent appears in the registry, the shared
`install_cmd` installs omnigent itself (+ node + uv + tmux, plus the harmless
`pi` CLI), and the per-harness `session_factory` resolves — but each harness's
**own** CLI install + model routing are the **NEXT step** and are not yet wired.
Do not assume a non-pi agent runs until its CLI is provisioned. The per-harness
factory is `omnigent.agent:build_omnigent_<slug>` (underscores in the function
name, e.g. `build_omnigent_openai_agents`); `build_omnigent_agent` is kept as a
back-compat alias that defaults to the `pi` harness.

### Completeness & provenance

The 22 harnesses above are the **complete** canonical set, taken from the upstream
source — every `omnigent/inner/*_harness.py` plus the alias map in
`harness_aliases.py` — not the shorter list in omnigent's own README. The
`*-native` rows are omnigent's native drivers (each a distinct harness in the
source), now **registered** as their own `omnigent-<slug>-native` agents rather
than left as run-mode notes. Aliases resolve to canonical values (e.g. `opencode`
→ `opencode-native`, `claude` → `claude-sdk`, `qwen-code` → `qwen`), so we register
the canonical `--harness` value for each. Re-run the source check if upstream adds a
harness:
`gh api repos/omnigent-ai/omnigent/git/trees/main?recursive=1 --jq '.tree[].path' | grep 'inner/.*_harness.py'`.

Why in-sandbox subprocess and not the in-process `omnigent-client` SDK:
Omnigent's runner pins `starlette<1` and ships a conflicting FastAPI/litellm
stack, so importing it into the BenchFlow host process (which runs a
litellm/starlette-1.x usage proxy) breaks at import. The supported path is to
install omnigent under its own `uv tool` env **in the sandbox** and shell its
one-shot CLI there.

## Requirements

- **A BenchFlow build with the session-factory seam.** Omnigent is non-ACP, so
  the kernel must carry: `AgentConfig.session_factory`, `"session-factory"` in
  `registry.VALID_PROTOCOLS` (so `register_agent` accepts the protocol), and
  `rollout._connect_session_factory` (to resolve + connect the entrypoint). This
  seam is **not** in published `0.6.x`. Without it, `register()` logs a warning
  and returns `None` (import stays safe).
- **x86_64 sandbox** (e.g. Daytona). Omnigent's dependency `cel-expr-python` has
  no `linux-aarch64` wheel, so it installs on x86_64 but not arm64 (local
  Apple-Silicon docker). It also has no `cp314` wheel, so the install pins
  `--python 3.12`.
- **Internet egress** for the model/provider calls (BenchFlow's resolved
  provider gateway).
- **Usage tracking ON** (`auto` — the default — or `required`; *not* `off`).
  omnigent's model calls run *inside the sandbox*, so they must route through
  BenchFlow's litellm usage proxy to be captured. The adapter writes whatever
  `BENCHFLOW_PROVIDER_BASE_URL` resolves to into omnigent's config, so with usage
  tracking on that is the proxy and tokens are captured. With
  `usage_tracking="off"` the calls go direct, no tokens are captured, and (on
  BenchFlow 0.7) the zero-activity guard — zero tokens **and** zero tool calls —
  treats the run as a silent provider failure and nulls the reward.

## Install

```bash
pip install "omnigent-benchflow @ git+https://github.com/benchflow-ai/agents#subdirectory=omnigent"
```

## Usage

Importing the package registers the `omnigent-*` agents with BenchFlow:

```python
import omnigent  # registers omnigent-{pi,claude,codex,cursor,opencode,hermes,openai-agents}

from benchflow import SDK
# omnigent-pi is the fully-worked one (verified end-to-end).
await SDK().run(task_path="...", agent="omnigent-pi", model="deepseek/deepseek-chat")
```

Prefer no import side effects? Call `omnigent.register()` explicitly. It returns
the **list** of created `AgentConfig` objects on success, or `None` (with a
warning) on a BenchFlow that lacks the session-factory seam.

The benchmark model is forwarded per turn via `omnigent run --model`
(read from `BENCHFLOW_PROVIDER_MODEL`); credentials + gateway come from the
resolved `BENCHFLOW_PROVIDER_*` and are written into the in-sandbox
`~/.omnigent/config.yaml` at connect time.

## How it works

- `register.py` registers one `omnigent-<slug>` per entry in `HARNESSES`, each
  with `protocol="session-factory"`, a descriptive per-harness `launch_cmd`, and
  the shared `install_cmd` that provisions Omnigent + the `pi` harness CLI inside
  the sandbox (see below). Each sets
  `session_factory = "omnigent.agent:build_omnigent_<slug>"`.
- `agent.py` (`OmnigentAgent.__init__(harness=...)` / `.connect`) writes
  Omnigent's credential store into the sandbox at `~/.omnigent/config.yaml` — a
  single `gateway`-kind provider pointing the harness at the BenchFlow provider
  endpoint over the OpenAI `chat` wire, with the **literal** API key (an env-ref
  does *not* resolve in the daemon-spawned runner) and the base URL normalized to
  end with `/v1`. The per-harness factories `build_omnigent_<slug>` bind the
  `--harness` value; `build_omnigent_agent` is the back-compat alias (defaults
  `pi`).
- `session.py` (`OmnigentSession.prompt`) shells one
  `omnigent run --harness <value> --model <model> -p <text>` per turn with cwd
  `/app` (the task root), stopping any stale daemon first. It re-emits a
  `user_message` + final `agent_message` as trajectory events.

The `install_cmd`, in the sandbox: isolated Node.js + **symlink `node`/`npm`/`npx`
onto `/usr/local/bin`** (the `pi` CLI is a `#!/usr/bin/env node` script and the
runner spawns it from a fresh shell that does not inherit PATH — without `node`
on the bare PATH, `pi` never launches and writes no file); install **tmux** (the
runner auto-creates a per-conversation REPL terminal and hard-fails without it);
install `uv`; `uv tool install omnigent` in its own venv (`--python 3.12`);
`npm i -g @earendil-works/pi-coding-agent` + symlink; then verify
`omnigent`/`pi`/`node`/`tmux` all resolve.

> Note: omnigent's *managed* REPL terminal additionally wants `bwrap`
> (bubblewrap) to sandbox itself; that auto-create logs a **non-fatal** ERROR
> inside the BenchFlow sandbox (double-sandboxing is neither available nor
> needed). The `pi` harness runs its own shell to do the task work, so this does
> not block file writes.

## Verification

Only `omnigent-pi` is verified — the other `omnigent-*` agents are listed but
their own CLI install + model routing are not yet wired (see
[Harnesses](#harnesses)), so they are unverified.

`omnigent-pi` scores **reward 1.0** end-to-end in `bench eval` on a Daytona
(x86_64) sandbox with `deepseek/deepseek-chat`, against a BenchFlow carrying the
session-factory seam (validated on the 0.7 line, `trajectory_source="session"`):

- **hello-world** (toy file-write) — full pipeline green: install → connect →
  `omnigent run` → verifier.
- **citation-check** (real, medium research task) — read a BibTeX file, query
  citation APIs over the network, detect the hallucinated entries, write sorted
  JSON. All 9 verifier tests passed (all three fake citations detected, correct
  count, clean titles).

Both runs used the default (`auto`) usage tracking so omnigent routed through
the proxy; see Requirements on why `usage_tracking="off"` nulls the reward.

Known limitation — coarse trajectories: the stdout-parsing adapter emits only
the prompt + final agent message, so per-tool-call granularity is absent
(`n_tool_calls` reads 0 even though the harness used tools). The reward is real;
the trajectory just isn't step-auditable. This is **inherent to omnigent's
headless one-shot mode**, not an easy fix: as of `omnigent==0.1.0`, the `-p`
one-shot path exposes no tool-call stream — `--debug-events` only drives the
interactive REPL event tape, `--log` is *rejected* with `-p`
("only supported in interactive REPL mode"), and the server's `chat.db` is torn
down on exit. Surfacing tool calls therefore requires a larger rework: keep the
local server alive and poll its REST API (`/v1/sessions/<conv>/items`) for the
turn's items, rather than the current fire-and-forget `omnigent run -p`. Tracked
as a follow-up; the one-shot path is kept because it is simple and proven.

Per-turn timeout: `omnigent run`'s sandbox-exec backstop is
`BENCHFLOW_OMNIGENT_RUN_TIMEOUT_SEC` (default 1800s). The *authoritative* per-turn
bound is the task's own `[agent] timeout_sec` (the kernel wraps `prompt()` in
`asyncio.wait_for`); this backstop only sits above it so a hung exec can't run
unbounded — keep it ≥ your largest task budget.

## Develop

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests
pytest   # registration tests; skip cleanly on a benchflow without the seam
```

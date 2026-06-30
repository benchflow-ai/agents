# omnigent

[Databricks Omnigent](https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents)
as a [BenchFlow](https://github.com/benchflow-ai/benchflow) agent — the Omnigent
meta-harness wired in through the public `benchflow.register_agent` extension
point, maintained outside the core framework. The package lists **one BenchFlow
agent per Omnigent `--harness`** (see [Harnesses](#harnesses)). **`omnigent-pi`
and `omnigent-claude` are verified end-to-end on the BenchFlow provider gateway
(citation-check reward 1.0, docker + daytona)**; `omnigent-codex` is wired but
blocked upstream (the gateway's `/v1/responses` route); the rest are listed with
honest per-harness status below.

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
`omnigent-<slug>` and wired to `omnigent run --harness <value>`. The list keeps
the **full** upstream set — derived from the source of truth
([`omnigent/inner/*_harness.py`](https://github.com/omnigent-ai/omnigent/tree/main/omnigent/inner)
+ `harness_aliases.py`) — but **only the 8 values omnigent 0.1.0 actually exposes
launch** (`pi`, `claude-sdk`, `claude-native`, `codex`, `codex-native`,
`openai-agents`, `open-responses`, `databricks_supervisor`); the rest are
upstream-only and rejected as "Unsupported harness" by the pinned omnigent.
Status is tracked per harness in `register._HARNESS_STATUS` — update it as
harnesses get wired.

Status legend: **WORKED** (verified e2e, reward 1.0) · **blocked** (wired,
upstream/gateway gap) · **WIP** (wired, no scoreable run yet) · **listed** (real
0.1.0 harness, not yet wired) · **upstream-only** (not a 0.1.0 `--harness`).

**Vendor SDK / CLI harnesses** (drive the vendor's own CLI, pointed at the BenchFlow gateway):

| BenchFlow agent | `--harness` value | status |
| --- | --- | --- |
| `omnigent-pi` | `pi` | **WORKED** — verified e2e (reward 1.0); `pi` CLI + gateway `/v1/chat/completions` |
| `omnigent-claude` | `claude-sdk` | **WORKED** — verified e2e (reward 1.0); Claude Code CLI (`@anthropic-ai/claude-code`) + gateway `/v1/messages` (`ANTHROPIC_BASE_URL`/`_AUTH_TOKEN`/`_MODEL`) |
| `omnigent-codex` | `codex` | **blocked** — codex CLI (pinned `@openai/codex@~0.128`) + responses-wire provider config wired, but codex is responses-only and the gateway `/v1/responses` route 404s the model (needs a benchflow-core litellm fix) |
| `omnigent-openai-agents` | `openai-agents` | listed — real 0.1.0 harness; needs the OpenAI Agents SDK / responses routing (NEXT step) |
| `omnigent-open-responses` | `open-responses` | listed — real 0.1.0 harness; gateway `/v1/responses` routing (NEXT step) |
| `omnigent-databricks-supervisor` | `databricks_supervisor` | listed — real 0.1.0 harness; omnigent's own supervisor (NEXT step) |
| `omnigent-cursor` | `cursor` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-opencode` | `opencode-native` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-hermes` | `hermes` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-goose` | `goose` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-qwen` | `qwen` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-kimi` | `kimi` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-copilot` | `copilot` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-antigravity` | `antigravity` | upstream-only — not in omnigent 0.1.0 |

**omnigent native drivers** (omnigent runs the agent directly, no vendor SDK):

| BenchFlow agent | `--harness` value | status |
| --- | --- | --- |
| `omnigent-claude-native` | `claude-native` | **WIP** — Claude Code CLI + gateway `ANTHROPIC_*` wired; the native driver launches but does not yet surface a scoreable run |
| `omnigent-codex-native` | `codex-native` | **blocked** — same gateway `/v1/responses` limitation as `codex` |
| `omnigent-pi-native` | `pi-native` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-cursor-native` | `cursor-native` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-hermes-native` | `hermes-native` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-goose-native` | `goose-native` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-qwen-native` | `qwen-native` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-kimi-native` | `kimi-native` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-antigravity-native` | `antigravity-native` | upstream-only — not in omnigent 0.1.0 |
| `omnigent-kiro-native` | `kiro-native` | upstream-only — not in omnigent 0.1.0 |

**How a vendor harness rides the gateway:** `OmnigentAgent.connect` installs the
harness's own CLI (via the per-harness `register._HARNESS_SETUP` install snippet)
and points it at the resolved BenchFlow provider gateway — codex via a
`~/.codex/config.toml` custom provider on the OpenAI `responses` wire, claude via
`ANTHROPIC_BASE_URL`/`_AUTH_TOKEN`/`_MODEL` env (root base url, the client appends
`/v1/messages`). The per-harness factory is
`omnigent.agent:build_omnigent_<slug>` (underscores; e.g.
`build_omnigent_openai_agents`); `build_omnigent_agent` is a back-compat alias
defaulting to `pi`. **upstream-only** rows are kept forward-looking but the pinned
omnigent rejects them — do not assume a harness runs until its row says WORKED.

### Completeness & provenance

The harnesses above keep the **full** upstream canonical set (every
`omnigent/inner/*_harness.py` + the `harness_aliases.py` map) so new ones surface
in the registry, **plus** the two real 0.1.0 harnesses that the upstream-file
scan misses (`open-responses`, `databricks_supervisor`). Only the 8 values
omnigent 0.1.0 exposes actually launch (`register._REAL_OMNIGENT_HARNESSES`); the
upstream-only rows are forward-looking and rejected by the pinned omnigent until a
newer omnigent ships them. Aliases resolve to canonical values (e.g. `opencode` →
`opencode-native`, `claude` → `claude-sdk`, `qwen-code` → `qwen`), so we register
the canonical `--harness` value for each. Re-check the live harness set with
`omnigent run --harness x` (the error lists the supported values), or the source:
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
import omnigent  # registers the omnigent-<harness> agents (pi + claude verified; see Harnesses)

from benchflow import SDK
# omnigent-pi and omnigent-claude are verified end-to-end (reward 1.0).
await SDK().run(task_path="...", agent="omnigent-claude", model="deepseek/deepseek-v4-flash")
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
  single `gateway`-kind provider pointing the `pi` harness at the BenchFlow
  provider endpoint over the OpenAI `chat` wire, with the **literal** API key (an
  env-ref does *not* resolve in the daemon-spawned runner) and the base URL
  normalized to end with `/v1`. **Vendor-CLI harnesses** additionally get their
  own CLI pointed at the gateway: codex via a `~/.codex/config.toml` custom
  provider on the `responses` wire (`supports_websockets=false`), claude via
  `ANTHROPIC_BASE_URL`/`_AUTH_TOKEN`/`_MODEL` env (the resolved base with its
  trailing `/v1` stripped, since the Anthropic client appends `/v1/messages`).
  It also plumbs `BENCHFLOW_AGENT_CWD` so the run lands in the verifier's
  workspace. The per-harness factories `build_omnigent_<slug>` bind the
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

`omnigent-pi` and `omnigent-claude` are verified **end-to-end** in `bench eval`
on **citation-check** (a real research task: read a BibTeX file, query citation
APIs over the network, detect the hallucinated entries, write sorted JSON) with
`deepseek/deepseek-v4-flash` through the BenchFlow provider gateway:

| agent | docker | daytona | route |
| --- | --- | --- | --- |
| `omnigent-pi` | reward **1.0** | reward 0.0¹ | gateway `/v1/chat/completions` |
| `omnigent-claude` | reward **1.0** | reward **1.0** | gateway `/v1/messages` |

¹ pi/daytona ran through with real activity (253k tokens, no error) but the model
missed the answer on that attempt — stochastic, not a harness failure. The
connect/session path has no docker/daytona branch, so behaviour is sandbox-agnostic.

All four runs route through the proxy and capture the **raw `llm_trajectory.jsonl`**
(real model round-trips) alongside `acp_trajectory.jsonl`. They use the default
(`auto`) usage tracking; see Requirements on why `usage_tracking="off"` nulls the
reward. `omnigent-codex` is wired but blocked upstream (see [Harnesses](#harnesses)).

> The `benchflow-experiment-review` validator marks every omnigent run
> `unhealthy` for the **same** reason — *"missing or zero tool usage metadata"*
> (`n_tool_calls=0`) — uniformly across pi/claude × docker/daytona. That is the
> coarse-trajectory limitation below (omnigent's one-shot `-p` mode surfaces no
> per-tool-call stream), **not** a routing gap: the reward and the raw
> `llm_trajectory` are real.

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

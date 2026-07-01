# omnigent

[Databricks Omnigent](https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents)
as a [BenchFlow](https://github.com/benchflow-ai/benchflow) agent — the Omnigent
meta-harness wired in through the public `benchflow.register_agent` extension
point, maintained outside the core framework. The package hosts **all 22 harnesses
the pinned omnigent (`0.3.0`) dispatches** — one BenchFlow agent per
`omnigent run --harness <value>`, defined one-spec-per-file in
[`omnigent/harnesses/`](src/omnigent/harnesses) (mirroring omnigent's own
`inner/*_harness.py` + `harness_aliases.py`) so a future omnigent bump is a
one-directory migration. **`omnigent-pi` and `omnigent-claude` are verified
end-to-end on the BenchFlow provider gateway (citation-check reward 1.0)**;
`omnigent-openai-agents` runs end-to-end with the raw `llm_trajectory` captured;
`omnigent-codex` is gateway-wired but blocked (the gateway has no `/v1/responses`
route); the remaining vendor harnesses register + dispatch but need a vendor CLI +
key the gateway doesn't serve (**needs-vendor**). See [Harnesses](#harnesses).

Every harness rides the **same** path: `connect()` writes ONE gateway provider
into the sandbox `~/.omnigent/config.yaml`, and omnigent's own runner routes each
harness to its provider family (openai chat / anthropic messages) and emits the
per-harness `HARNESS_*_GATEWAY_*` env vars itself. The adaptor does not
re-implement omnigent's routing.

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

One BenchFlow agent is registered per harness omnigent **0.3.0** dispatches (its
`runtime.harnesses._HARNESS_MODULES`, aliases folded — `claude`→`claude-sdk`,
`opencode`→`opencode-native`, …). Named `omnigent-<slug>`, wired to `omnigent run
--harness <value>`. Each harness is one spec module in
[`omnigent/harnesses/`](src/omnigent/harnesses) (the single source of truth); the
`HARNESSES` table, the `build_omnigent_*` factories, and the status/install maps
all **derive** from it. Adding/migrating a harness = one spec module.

**Registered ≠ runs on the gateway.** The BenchFlow deepseek gateway serves only
the openai-chat + anthropic-messages wires, and omnigent applies our provider
only to harnesses in its `provider_config._HARNESS_FAMILY` (plus `pi`). So most of
the vendor harnesses register + dispatch on 0.3.0 but fall back to their own
vendor CLI + API key — flagged **needs-vendor**, not silently broken.

Status legend: **WORKED** (verified e2e, reward 1.0) · **RUNS** (e2e, raw
`llm_trajectory` captured, reward < 1.0) · **blocked** (gateway-wired, wire not
served) · **WIP** (gateway-wired, no scoreable run yet) · **needs-vendor**
(dispatches, but needs a vendor CLI + key the gateway does not serve).

| BenchFlow agent(s) | `--harness` value | status |
| --- | --- | --- |
| `omnigent-pi` | `pi` | **WORKED** — reward 1.0; gateway openai/pi wire |
| `omnigent-claude` | `claude-sdk` | **WORKED** — reward 1.0; Claude Code CLI, gateway anthropic `/v1/messages` |
| `omnigent-openai-agents` | `openai-agents` | **RUNS** — gateway openai chat, `llm_trajectory` captured (bundled SDK, no extra CLI) |
| `omnigent-codex` · `-codex-native` | `codex` · `codex-native` | **blocked** — `@openai/codex` gateway-wired but Responses wire; gateway has no `/v1/responses` (#38) |
| `omnigent-claude-native` | `claude-native` | **WIP** — Claude Code CLI, gateway anthropic wire; native driver launches, no scoreable run yet |
| `omnigent-qwen` · `-antigravity` | `qwen` · `antigravity` | **WIP** — openai-compatible wire, our provider applies; need their CLI to launch |
| `omnigent-pi-native` · `-cursor(-native)` · `-kimi(-native)` · `-qwen-native` · `-goose(-native)` · `-hermes(-native)` · `-antigravity-native` · `-copilot` · `-kiro-native` · `-opencode-native` | (12 vendor/native) | **needs-vendor** — dispatch on 0.3.0 but use a wire the gateway doesn't serve (need vendor CLI + key) |

**How a harness rides the gateway:** `OmnigentAgent.connect` writes one
`gateway`-kind provider into `~/.omnigent/config.yaml` carrying both families the
gateway serves — `openai` (chat: pi / openai-agents / codex) and `anthropic`
(messages: claude / claude-native). omnigent's runner resolves each harness to
its family (`_PROVIDER_HARNESS_FAMILY`) and emits the `HARNESS_*_GATEWAY_*` env
vars itself, so there is **no per-harness wiring in `connect()`**. Vendor CLIs
(codex, claude) are installed via the per-harness `register._HARNESS_SETUP`
snippet. The per-harness factory is `omnigent.agent:build_omnigent_<slug>`
(underscores; e.g. `build_omnigent_openai_agents`); `build_omnigent_agent` is a
back-compat alias defaulting to `pi`.

### Provenance

The harness set is **version-dependent** — 0.1.0 dispatched ~6, 0.2.0 ten, 0.3.0
all 22. We register from `omnigent.runtime.harnesses._HARNESS_MODULES` (what
`omnigent run --harness X` can actually **dispatch**), NOT the `--harness`
validator set (`OMNIGENT_HARNESSES`, which also lists non-dispatchable entries) and
NOT omnigent's website/blog (which advertises an inconsistent ~3–6 aspirational
names). On a pin bump, re-mirror the spec modules in
[`omnigent/harnesses/`](src/omnigent/harnesses) + `harnesses/_aliases.py` against
the new release's `_HARNESS_MODULES` + `harness_aliases.py`.

Re-check against the installed release: print `_HARNESS_MODULES`, or run `omnigent
run --harness x` (the error lists validator-accepted values), or scan the source:
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
  Omnigent's credential store into the sandbox at `~/.omnigent/config.yaml` — one
  `gateway`-kind provider carrying both families the gateway serves: `openai`
  (chat, base URL normalized to `/v1`) and `anthropic` (messages, the ROOT base —
  the Anthropic client appends `/v1/messages`). Both use the **literal** API key
  (an env-ref does *not* resolve in the daemon-spawned runner). omnigent's runner
  routes each harness to its family from this one provider — there is no
  per-harness wiring in `connect()`. It also plumbs `BENCHFLOW_AGENT_CWD` so the
  run lands in the verifier's workspace. The per-harness factories
  `build_omnigent_<slug>` bind the `--harness` value; `build_omnigent_agent` is
  the back-compat alias (defaults `pi`).
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

Known behaviour — flaky daemon startup (0.3.0): omnigent 0.3.0's host-daemon
occasionally exits before its local server becomes ready in the
resource-constrained sandbox (`omnigent run` aborts with "The local daemon exited
before its Omnigent server became ready"). This is a transient startup race — the
same harness scores reward 1.0 once the daemon comes up — so `OmnigentSession`
**retries** the run on that specific signature (`omnigent stop` first), up to
`BENCHFLOW_OMNIGENT_STARTUP_ATTEMPTS` (default 4). A real agent failure never
matches the retry markers and runs once.

Known limitation — coarse trajectories: the stdout-parsing adapter emits only
the prompt + final agent message, so per-tool-call granularity is absent
(`n_tool_calls` reads 0 even though the harness used tools). The reward is real;
the trajectory just isn't step-auditable. This is **inherent to omnigent's
headless one-shot mode**, not an easy fix: the `-p` one-shot path exposes no
tool-call stream — `--debug-events` only drives the
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

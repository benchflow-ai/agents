# omnigent

[Databricks Omnigent](https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents)
as a [BenchFlow](https://github.com/benchflow-ai/benchflow) agent — the
Omnigent `pi` meta-harness wired in through the public `benchflow.register_agent`
extension point, maintained outside the core framework.

Unlike the other agents in this repo, Omnigent does **not** speak ACP. It rides
BenchFlow's non-ACP **Session** path: the kernel resolves a `session_factory`
entrypoint and drives one `omnigent run --harness pi` turn per prompt, executed
**inside the sandbox** via `Sandbox.exec`. ACP is the *first* concrete `Session`
implementation; this is a *second*.

```text
benchflow kernel ──session-factory──▶ OmnigentAgent.connect()         (host, in-process)
                                         └─ writes ~/.omnigent/config.yaml into sandbox
                 ──prompt(text)───────▶ OmnigentSession.prompt()       (host, in-process)
                                         └─ sandbox.exec: `omnigent run --harness pi -p …`
                                                              └─ omnigent server + pi runner
                                                                   └─ writes files in /app
```

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
  and returns `None` (import stays safe) — the same way `acp-registry` degrades
  without its `acp_model_via_env` flag.
- **x86_64 sandbox** (e.g. Daytona). Omnigent's dependency `cel-expr-python` has
  no `linux-aarch64` wheel, so it installs on x86_64 but not arm64 (local
  Apple-Silicon docker). It also has no `cp314` wheel, so the install pins
  `--python 3.12`.
- **Internet egress** for the model/provider calls (BenchFlow's resolved
  provider gateway).

## Install

```bash
pip install "omnigent-benchflow @ git+https://github.com/benchflow-ai/agents#subdirectory=omnigent"
```

## Usage

Importing the package registers the agent with BenchFlow:

```python
import omnigent  # registers omnigent-pi (non-ACP, session-factory)

from benchflow import SDK
await SDK().run(task_path="...", agent="omnigent-pi", model="deepseek/deepseek-chat")
```

Prefer no import side effects? Call `omnigent.register()` explicitly. It returns
the `AgentConfig` on success, or `None` (with a warning) on a BenchFlow that
lacks the session-factory seam.

The benchmark model is forwarded per turn via `omnigent run --model`
(read from `BENCHFLOW_PROVIDER_MODEL`); credentials + gateway come from the
resolved `BENCHFLOW_PROVIDER_*` and are written into the in-sandbox
`~/.omnigent/config.yaml` at connect time.

## How it works

- `register.py` registers `omnigent-pi` with `protocol="session-factory"`, a
  descriptive `launch_cmd`, and an `install_cmd` that provisions Omnigent +
  the `pi` harness CLI inside the sandbox (see below). It sets
  `session_factory = "omnigent.agent:build_omnigent_agent"`.
- `agent.py` (`OmnigentAgent.connect`) writes Omnigent's credential store into
  the sandbox at `~/.omnigent/config.yaml` — a single `gateway`-kind provider
  pointing `pi` at the BenchFlow provider endpoint over the OpenAI `chat` wire,
  with the **literal** API key (an env-ref does *not* resolve in the
  daemon-spawned runner) and the base URL normalized to end with `/v1`.
- `session.py` (`OmnigentSession.prompt`) shells one
  `omnigent run --harness pi --model <model> -p <text>` per turn with cwd `/app`
  (the task root), stopping any stale daemon first. It re-emits a
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

`omnigent-pi` scores **reward 1.0** end-to-end in `bench eval` on a Daytona
(x86_64) sandbox with `deepseek/deepseek-chat`:

- **hello-world** (toy file-write) — full pipeline green: install → connect →
  `omnigent run` → verifier.
- **citation-check** (real, medium research task) — read a BibTeX file, query
  citation APIs over the network, detect the hallucinated entries, write sorted
  JSON. All 9 verifier tests passed (all three fake citations detected, correct
  count, clean titles).

Known limitation: the stdout-parsing adapter emits only the prompt + final
agent message, so per-tool-call trajectory granularity is coarse (`n_tool_calls`
reads 0 even though the harness used tools). The reward is real; richer
trajectories would come from parsing omnigent's `--debug-events` JSONL.

## Develop

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests
pytest   # registration tests; skip cleanly on a benchflow without the seam
```

# opencode TUI (`mini-opencode`)

!!! abstract "Overview"

    * `mini-opencode` runs mini-SWE-agent behind [opencode](https://opencode.ai)'s terminal UI.
    * A small Python server speaks opencode's HTTP+SSE protocol with mini-SWE-agent as the backend; the real opencode TUI attaches to it and renders each agent step as native messages and tool calls.
    * This fork ships a **self-contained, prebuilt TUI binary**, so no external opencode repository or `bun` is required at runtime.

!!! warning "Platform"

    The bundled TUI binary is built for **macOS arm64** (`darwin-arm64`). On other platforms, rebuild it (see [Rebuilding the TUI binary](#rebuilding-the-tui-binary)).

## Quick start

Install the optional dependencies and set a model API key:

```bash
pip install -e ".[opencode]"     # adds starlette + uvicorn
export ANTHROPIC_API_KEY=...      # or OPENAI_API_KEY / GEMINI_API_KEY / ...
```

Launch the server and the TUI together in one window:

```bash
mini-opencode --attach --cwd /path/to/scratch/dir
```

Pick a model, type a task, and mini-SWE-agent runs its loop — the bash commands show up as native opencode tool calls. Quitting the TUI stops the server.

!!! danger "The agent runs bash locally without confirmation"

    In this mode opencode owns the UI, so the agent executes commands directly in `--cwd` (default: the current directory). Point `--cwd` at a sandbox/scratch directory if you don't want it touching real files.

!!! tip "Running from source (no install)"

    ```bash
    MSWEA_SILENT_STARTUP=1 PYTHONPATH=src python3 -m minisweagent.run.opencode --attach --cwd /path/to/scratch/dir
    ```

## Command line options

- `--attach`: start the server **and** launch the TUI in one process (recommended). Without it, only the server runs and you attach a TUI yourself.
- `--cwd`: working directory the agent operates in (default: current directory).
- `--port`: server port (default: `4747`).
- `--opencode-dir`: directory to launch the TUI from — only needed when pointing `OPENCODE_CMD` at a dev `bun src/index.ts` TUI instead of the bundled binary.

The model selected in the TUI maps to a litellm model name as `providerID/modelID` (e.g. `anthropic/claude-sonnet-4-6`).

## Which TUI gets launched

`--attach` resolves the TUI command in this order:

1. `OPENCODE_CMD` if set (e.g. a dev build: `bun --conditions=browser /path/to/opencode/packages/opencode/src/index.ts`).
2. The bundled binary at `src/minisweagent/run/opencode/bin/opencode`.
3. A global `opencode` on your `PATH`.

## Two-terminal mode

Useful for debugging — run the pieces separately:

```bash
# terminal 1 — server
mini-opencode --port 4747 --cwd /path/to/scratch/dir
# terminal 2 — TUI (bundled binary)
src/minisweagent/run/opencode/bin/opencode attach http://127.0.0.1:4747
```

Server activity is logged to `/tmp/mini-opencode.log` (`prompt received`, `agent start`/`agent done`, errors). If no API key is set, the server prints a warning at startup and the TUI shows the auth error inside the conversation.

## Rebuilding the TUI binary

The bundled binary is compiled from [opencode](https://github.com/anomalyco/opencode) (with mini-SWE-agent branding). To rebuild for your platform, inside the opencode repo's `packages/opencode`:

```bash
bun run build --single --skip-embed-web-ui   # requires bun >= 1.3.14
# -> dist/opencode-<os>-<arch>/bin/opencode
```

Copy the result to `src/minisweagent/run/opencode/bin/opencode`.

## How it works

- `src/minisweagent/run/opencode/server.py` — a [Starlette](https://www.starlette.io/) server implementing the subset of opencode's protocol the TUI needs (config/providers, sessions, messages, and the `/global/event` SSE stream).
- `bridge.py` — subclasses [`DefaultAgent`](../../src/minisweagent/agents/default.py) and translates each step into opencode message/part events (assistant text + a `bash` tool call going `running` → `completed`).
- The TUI is opencode's real UI, so the look and feel match opencode (minus opencode-specific features such as its own model subscriptions, which are intentionally not wired up).

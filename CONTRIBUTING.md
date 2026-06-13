# Contributing

Thanks for your interest! This is a small monorepo of agent packages —
`mini-swe-acp`, `mini-swe-code`, and the `ai-sdk/` group (`acp`, `harness-pi`,
`harness-codex`, `harness-claude-code`) — each builds, tests, and ships on its
own. The `ai-sdk/*` packages pair a pure-JS ACP server (`server.mjs`) with a
small Python `register.py` that wires the agent into BenchFlow. New agents:
scaffold + parity-check with the [`adaptation-parity`](skills/adaptation-parity)
skill (`docs/adaptation.md`, `docs/parity.md`).

## Dev setup

### mini-swe-acp (Python ≥3.12)

```bash
cd mini-swe-acp
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q                                        # 12 tests, no API keys needed
ruff check src tests && ruff format --check src tests
```

### mini-swe-code (Python ≥3.10)

```bash
cd mini-swe-code
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev,opencode]"

# Key-free test subset (what CI runs):
MSWEA_SILENT_STARTUP=1 pytest -q \
  tests/models tests/agents tests/config tests/utils \
  tests/run/test_batch_progress.py tests/run/test_inspector.py \
  tests/run/test_run_hello_world.py tests/run/test_local.py \
  tests/run/test_save.py

ruff check src tests
```

The full upstream suite additionally needs provider API keys and container
runtimes (podman, bubblewrap, apptainer) — not required for most changes.

### ai-sdk/* (Python ≥3.12 + Node)

```bash
cd ai-sdk/acp        # or harness-pi / harness-codex / harness-claude-code
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q                                        # key-free; no sandbox/model needed
ruff check src tests
node --check src/*/server.mjs                    # JS server syntax
```

The JS `server.mjs` is base64-deployed into the benchflow sandbox by
`register.py`'s install command (its npm deps are installed there). Running it
against a live benchmark needs Node, a sandbox (docker/daytona), and a model.

## CI

Root `.github/workflows/` runs per-package tests (path-filtered), ruff
(pinned to the `.pre-commit-config.yaml` version), and a markdown link check
on PRs. Please make sure the relevant package's tests and lint pass locally
before opening a PR.

`pre-commit install` at the repo root enables the same hooks (ruff,
ruff-format, typos) locally.

## Conventions

- Keep changes scoped to one package per PR when possible.
- `mini-swe-code/src/minisweagent/` tracks upstream mini-swe-agent — prefer
  upstream-compatible changes there (the opencode integration lives in
  `src/minisweagent/run/opencode/` and is ours).
- Style follows the existing code: type annotations, `pathlib`, minimal
  comments (see `.github/copilot-instructions.md`).

## Gotchas

- `mini-swe-code/.gitignore` contains `*.traj.json`, but
  `tests/test_data/{local,github_issue}.traj.json` are tracked test fixtures
  (force-added upstream). If you ever re-add the tree wholesale, use
  `git add -f` for those two or two end-to-end tests fail with
  `FileNotFoundError`.
- The bundled opencode TUI binary
  (`mini-swe-code/src/minisweagent/run/opencode/bin/opencode`, ~82 MB,
  macOS arm64) is committed as a normal blob. Rebuild recipe:
  [docs/usage/opencode_tui.md](mini-swe-code/docs/usage/opencode_tui.md).

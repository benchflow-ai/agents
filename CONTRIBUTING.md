# Contributing

Thanks for your interest! This monorepo hosts several agent families. The
**buildable packages** each build, test, and ship on their own:

- **Self-contained** — `acp/mini-swe-acp` and `acp/mini-swe-code`.
- The **`ai-sdk/`** group — `acp`, `harness-pi`, `harness-codex`,
  `harness-claude-code`, `harness-deepagents`, `harness-opencode` — each pairs a
  pure-JS ACP server (`server.mjs`) with a small Python `register.py` that wires
  the agent into BenchFlow.
- **`omnigent/`** — its own Python package.

The **`acp-registry/`** family is different: the `acp-registry/` pip package
catalogs every agent, and most adapting agents ship a *declarative*
`acp/<id>/manifest.toml` instead — 38 of them, with no `server.mjs` of their own
(a couple, like `mimo-acp`, wrap a thin shim package).
They are classified in
[`acp-registry/src/acp_registry/catalog.py`](acp-registry/src/acp_registry/catalog.py)
(the live per-agent table is generated into
[`acp-registry/AGENTS.md`](acp-registry/AGENTS.md)) and validated by `contract/`.

New agents come two ways:

- **Declarative (now primary)** — write `acp/<id>/manifest.toml`, classify it in
  `acp-registry/src/acp_registry/catalog.py`, and let `contract/`
  (`manifest_schema.json` + the contract tests) validate it. See
  [`docs/tiers.md`](docs/tiers.md) for the tier the classification picks.
- **ai-sdk server** — scaffold a `server.mjs` + `register.py`, then parity-check
  with the [`adaptation-parity`](skills/adaptation-parity) skill
  (`docs/adaptation.md`, `docs/parity.md`).

## Dev setup

### mini-swe-acp (Python ≥3.12)

```bash
cd acp/mini-swe-acp
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q                                        # 12 tests, no API keys needed
ruff check src tests && ruff format --check src tests
```

### mini-swe-code (Python ≥3.10)

```bash
cd acp/mini-swe-code
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
cd ai-sdk/acp        # or harness-pi / harness-codex / harness-claude-code / harness-deepagents / harness-opencode
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q                                        # key-free; no sandbox/model needed
ruff check src tests
node --check src/*/server.mjs                    # JS server syntax
```

The JS `server.mjs` is base64-deployed into the benchflow sandbox by
`register.py`'s install command (its npm deps are installed there). Running it
against a live benchmark needs Node, a sandbox (docker/daytona), and a model.

### acp-registry (Python ≥3.12)

```bash
cd acp-registry
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q
```

`AGENTS.md` is generated from the catalog by `scripts/gen_agents_md.py` (from
`catalog.py` + `registry.snapshot.json`) — after any `catalog.py` or snapshot
change, regenerate it (`python scripts/gen_agents_md.py > AGENTS.md`) or the
`acp-registry` CI job's freshness check fails.

### contract (Python ≥3.12)

`contract/` is a manifest loader + tests (not a pip-installable package) that
validate every `acp/<id>/manifest.toml` against `manifest_schema.json`:

```bash
cd contract
pip install jsonschema pytest
PYTHONPATH=. pytest -q
```

### omnigent (Python ≥3.12)

```bash
cd omnigent
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q
```

## CI

Root `.github/workflows/` runs per-package tests (path-filtered) — including the
`acp-registry`, `parity`, `omnigent`, `mimo-acp`, and `ai-sdk` jobs — plus ruff
(pinned to the `.pre-commit-config.yaml` version) and a markdown
link check on PRs. The `acp-registry` job also fails the build when `AGENTS.md` is
stale, so regenerate it after any `catalog.py` (or snapshot) edit (see the
acp-registry dev-setup above). The `contract/` tests are not yet a CI job — run
them locally. Please make sure the relevant package's tests and lint pass locally
before opening a PR.

`pre-commit install` at the repo root enables the same hooks (ruff,
ruff-format, typos) locally.

## Conventions

- Keep changes scoped to one package per PR when possible.
- `acp/mini-swe-code/src/minisweagent/` tracks upstream mini-swe-agent — prefer
  upstream-compatible changes there (the opencode integration lives in
  `src/minisweagent/run/opencode/` and is ours).
- Style follows the existing code: type annotations, `pathlib`, minimal
  comments (see `.github/copilot-instructions.md`).

## Gotchas

- `acp/mini-swe-code/.gitignore` contains `*.traj.json`, but
  `tests/test_data/{local,github_issue}.traj.json` are tracked test fixtures
  (force-added upstream). If you ever re-add the tree wholesale, use
  `git add -f` for those two or two end-to-end tests fail with
  `FileNotFoundError`.
- The bundled opencode TUI binary
  (`acp/mini-swe-code/src/minisweagent/run/opencode/bin/opencode`, ~82 MB,
  macOS arm64) is committed as a normal blob. Rebuild recipe:
  [docs/usage/opencode_tui.md](acp/mini-swe-code/docs/usage/opencode_tui.md).

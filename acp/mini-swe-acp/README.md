# mini-swe-acp

[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) as a
[BenchFlow](https://github.com/benchflow-ai/benchflow) agent: an
[ACP](https://agentclientprotocol.com) shim plus registration, maintained
outside the core framework.

mini-swe-agent is a deliberately minimal coding harness — a single `bash` tool,
one shared system prompt, no vendor editing primitives — which makes it ideal
for comparing models apples-to-apples on the same scaffold. This package wires
it into BenchFlow through the public `benchflow.register_agent` extension
point, so it runs like any built-in agent.

```text
benchflow ACP client ←stdio→ acp_shim.py ←in-process→ minisweagent DefaultAgent
                                          ←subprocess→  bash in the task cwd
```

## Install

```bash
pip install "mini-swe-acp @ git+https://github.com/benchflow-ai/agents#subdirectory=mini-swe-acp"
```

## Usage

Importing the package registers the agent with BenchFlow:

```python
import mini_swe_acp  # registers mini-swe (aliases: mini, minisweagent, mini-swe-agent)

from benchflow import SDK
await SDK().run(task_path="...", agent="mini-swe", model="openai/gpt-4o-mini")
```

Prefer no import side effects? Call `mini_swe_acp.register()` explicitly.

## How it works

- `register.py` registers `mini-swe` (aliases `mini`, `minisweagent`,
  `mini-swe-agent`) with install/launch commands. The install command creates an
  isolated venv in the sandbox, pip-installs `mini-swe-agent`, and base64-deploys
  `acp_shim.py`.
- `acp_shim.py` runs mini-swe's own `DefaultAgent` loop in-process against the
  task checkout and re-emits each step as ACP `session/update` notifications so
  BenchFlow captures the trajectory. The agent's bundled `mini.yaml` config is
  loaded verbatim (minus interactive keys), reproducing the upstream harness
  guardrails faithfully.
- The shim reads `BENCHFLOW_PROVIDER_*`, so the usage proxy and providers
  (incl. Azure Foundry, AWS Bedrock) work like the built-in agents.

Set `MINI_SWE_CONFIG=swebench.yaml` to mirror the SWE-bench config instead of
the generic `mini.yaml`.

## Develop

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests
pytest   # routing tests always run; sandbox tests skip without minisweagent
```

## Related

- [benchflow](https://github.com/benchflow-ai/benchflow) — the framework this
  plugs into (ACP runtime lives there under `src/benchflow/acp/`).
- [mini-swe-code](../mini-swe-code) — sibling package in this repo:
  mini-swe-agent with the opencode TUI (`mini-opencode`) for interactive use.

# benchflow-agents

Agent integrations for [BenchFlow](https://github.com/benchflow-ai/benchflow),
maintained outside the core framework.

Each integration registers itself with BenchFlow through the public
`benchflow.register_agent` extension point, so new agent harnesses can ship and
evolve here without changing the framework.

## Install

```bash
pip install benchflow-agents   # pulls benchflow as a dependency
```

## Usage

Importing the package registers every bundled agent with BenchFlow:

```python
import benchflow_agents  # registers mini-swe, ...

from benchflow import SDK
await SDK().run(task_path="...", agent="mini-swe", model="openai/gpt-4o-mini")
```

Prefer no import side effects? Call `benchflow_agents.register_all()` explicitly.

## Agents

| Agent | Aliases | Notes |
|-------|---------|-------|
| `mini-swe` | `mini`, `minisweagent`, `mini-swe-agent` | [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) — minimal single-bash-tool harness, multi-model via litellm. In-process ACP shim; reads `BENCHFLOW_PROVIDER_*` so the usage proxy and providers (incl. Azure Foundry, AWS Bedrock) work like the built-in agents. |

## Develop

```bash
pip install -e ".[dev]"
ruff check src tests && ruff format --check src tests
pytest                       # routing tests run; sandbox-only tests skip without minisweagent
```

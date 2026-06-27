# mini-swe-code

[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) bundled with an
[opencode](https://opencode.ai) terminal UI (`mini-opencode`), maintained by
[BenchFlow](https://github.com/benchflow-ai). Based on mini-swe-agent v2.3.0
(MIT, [LICENSE.md](LICENSE.md) kept verbatim). For running mini-swe as a
BenchFlow benchmark agent over ACP, see the sibling package
[mini-swe-acp](../mini-swe-acp).

## 1. Install (from source)

```bash
git clone https://github.com/benchflow-ai/agents.git
cd agents/mini-swe-code

# Create an isolated developer environment.
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[opencode,dev]"
```

## 2. Set your API key

> [!IMPORTANT]
> Do not commit API keys. Export them in your shell or keep them in a local
> `.env` file outside the repository.

```bash
export ANTHROPIC_API_KEY="<your-anthropic-api-key>"
```

For other providers, set the corresponding key instead, such as
`OPENAI_API_KEY` or `GEMINI_API_KEY`.

## 3. Verify the key with a direct LiteLLM request

```bash
python - <<'PY'
from litellm import completion

model = "anthropic/claude-opus-4-8"
response = completion(
    model=model,
    messages=[{"role": "user", "content": "Please answer exactly: startup ok"}],
    max_tokens=32,
)
print("model:", model)
print("answer:", response.choices[0].message.content.strip())
PY
```

## 4. Run a real `mini` end-to-end smoke test

This exercises the full path: CLI -> config loading -> LiteLLM -> model tool
call -> local bash execution -> trajectory save.

```bash
MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT=1 \
MSWEA_COST_TRACKING=ignore_errors \
mini -y --exit-immediately \
  -m anthropic/claude-opus-4-8 \
  -c mini.yaml \
  -c model.model_kwargs.max_tokens=1024 \
  -t 'This is an end-to-end smoke test. First run exactly this command: echo mini_e2e_ok. After observing it succeeds, finish by issuing exactly this command and nothing else: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT.' \
  -o /tmp/mini-swe-agent-opus48-e2e.traj.json
```

A successful run prints `mini_e2e_ok`, then exits after
`COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`, and saves the trajectory to
`/tmp/mini-swe-agent-opus48-e2e.traj.json`.

## 5. Run in the opencode TUI

Self-contained: a prebuilt opencode TUI binary is bundled, so no external
opencode repo or `bun` is needed at runtime.

```bash
mkdir -p /tmp/mini-swe-agent-scratch
mini-opencode --attach --cwd /tmp/mini-swe-agent-scratch
```

This opens opencode's TUI in the same terminal. Pick any model, type a task,
and the agent's bash steps render as native tool calls; errors show in the
conversation. The agent runs commands **locally without confirmation** in
`--cwd`, so point it at a scratch directory.

Notes: the bundled binary is **macOS arm64**; on other platforms rebuild it
(one-time). Full details: [docs/usage/opencode_tui.md](docs/usage/opencode_tui.md).

## 6. Local checks (optional)

```bash
MSWEA_SILENT_STARTUP=1 pytest -q \
  tests/models tests/agents tests/config tests/utils \
  tests/run/test_batch_progress.py tests/run/test_inspector.py

MSWEA_SILENT_STARTUP=1 pytest -q \
  tests/models/test_init.py tests/run/test_run_hello_world.py \
  tests/run/test_local.py tests/run/test_save.py

MSWEA_SILENT_STARTUP=1 ruff check src tests
```

## Troubleshooting

If you see `invalid x-api-key`, your shell is using an invalid or stale
`ANTHROPIC_API_KEY`; export a valid key again in the same shell. If you see
LiteLLM cost metadata errors for a newly released model, keep
`MSWEA_COST_TRACKING=ignore_errors` for the smoke test or add model pricing to a
LiteLLM registry file.

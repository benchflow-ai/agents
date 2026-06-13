# mini-computer-agent

A **minimal computer-use agent** — the computer-use analog of
[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent).

One screenshot → any vision model → one action → repeat. No vendor computer-use
tool, no separate grounding model, no tool-calling interface — just a linear
message history and `subprocess`. The whole agent is **~150 lines** in
[`core.py`](src/mini_computer_agent/core.py), and it runs with *any* vision model
via litellm. Because the scaffold is identical for every model, it's a
confound-free baseline for comparing models on desktop GUI tasks (the way
mini-swe-agent is for coding).

It is a **pure agent** — it carries no protocol/harness code.
[BenchFlow](https://github.com/benchflow-ai/benchflow)'s ACP layer wraps it for
benchmarking; nothing benchflow-specific lives here.

## Play with it

```python
from mini_computer_agent import run

# needs a desktop with scrot + xdotool on $DISPLAY, and a vision model key
result = run("Open the calculator and compute 2+2", model="gemini/gemini-3.5-flash")
print(result)
```

The loop, in `core.py`:

1. **See** — `scrot` captures the screen.
2. **Decide** — the vision model returns one JSON action
   (`click` / `double_click` / `right_click` / `type` / `key` / `scroll` /
   `done`). Coordinates are **[0,1000]-normalized** (the convention vision models
   like Gemini emit) and scaled to the real resolution before acting — getting
   this wrong mis-clicks by ~3× and looks like "the model can't ground."
3. **Act** — `xdotool` executes it.
4. Repeat until `done` (or the step budget).

`run(task, model, on_step=...)` exposes a per-step callback so a harness can
capture the trajectory.

## Benchmark with it

BenchFlow serves this agent over ACP and runs it on desktop/computer-use
benchmarks — the agent stays pure; the protocol wrapping is benchflow's.

## Develop

```bash
cd mini-computer-agent
uv venv .venv && source .venv/bin/activate
uv pip install -e '.[dev]'
pytest -q        # hermetic: parsing + coordinate scaling, no sandbox/model needed
ruff check src tests && ruff format --check src tests
```

## Validated

Run end-to-end on [BenchFlow](https://github.com/benchflow-ai/benchflow) + Daytona
(Linux sandbox + Chromium), served over ACP, model `gemini/gemini-3.5-flash`:

| Suite | Result |
| --- | --- |
| Single-target grounding — 1 synthetic + 5 MiniWoB++ (`click-button`/`link`/`dialog`/`option`/`tab`) | **6 / 6** |
| MiniWoB++ slice including multi-step (`enter-text`, `click-checkboxes`) | **6 / 7** |
| Overall | **7 / 8** |

- The `[0,1000] → pixel` coordinate scaling is the load-bearing detail: the model
  emits normalized coordinates that land on exact targets only after scaling
  (e.g. `195 → 250px`, `508 → 650px`, `820 → 1050px` on a 1280-wide screen) —
  used raw, every click misses by ~3× and the model looks like it "can't ground."
- Dogfooding drove a real fix: `enter-text` first failed (the model flailed on
  field focus); one line of prompt guidance (focus-then-type, verify-before-submit)
  took it to a clean pass in roughly half the steps. The remaining miss is
  `click-checkboxes` (multi-select thoroughness on small labels).

## License

Apache-2.0 — see [LICENSE](LICENSE).

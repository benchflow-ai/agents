"""BenchFlow agent spec for omnigent's ``openai-agents`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="openai-agents",
    harness_value="openai-agents",
    wire="openai-chat",
    native=False,
    gateway_served=True,
    status="runs",
    note=(
        "omnigent's bundled OpenAI-Agents SDK (in-process, no extra "
        "CLI); rides the gateway openai chat wire from the config.yaml "
        "provider (runs e2e, llm_trajectory captured)."
    ),
    install=None,
)

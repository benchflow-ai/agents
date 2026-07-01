"""BenchFlow agent spec for omnigent's ``qwen`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="qwen",
    harness_value="qwen",
    wire="openai-chat",
    native=False,
    gateway_served=True,
    status="wip",
    note=(
        "Alibaba Qwen Code CLI (OpenAI-compatible wire); our openai "
        "provider IS applied, but the qwen CLI is not auto-installed — "
        "install it to launch."
    ),
    install=None,
)

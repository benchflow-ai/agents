"""BenchFlow agent spec for omnigent's ``qwen`` harness."""

from __future__ import annotations

from omnigent.harnesses._installers import INSTALL_QWEN
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
        "provider IS applied, and the qwen CLI is now auto-installed "
        "(@qwen-code/qwen-code) so it launches on the gateway."
    ),
    install=INSTALL_QWEN,
)

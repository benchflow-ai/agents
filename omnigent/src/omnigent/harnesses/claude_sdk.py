"""BenchFlow agent spec for omnigent's ``claude-sdk`` harness."""

from __future__ import annotations

from omnigent.harnesses._installers import INSTALL_CLAUDE
from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="claude",
    harness_value="claude-sdk",
    wire="anthropic-messages",
    native=False,
    gateway_served=True,
    status="worked",
    note=(
        "Claude Code CLI (@anthropic-ai/claude-code); omnigent routes "
        "it to the gateway anthropic /v1/messages wire from the "
        "config.yaml provider. Verified reward 1.0."
    ),
    install=INSTALL_CLAUDE,
)

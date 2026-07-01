"""BenchFlow agent spec for omnigent's ``claude-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._installers import INSTALL_CLAUDE
from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="claude-native",
    harness_value="claude-native",
    wire="anthropic-messages",
    native=True,
    gateway_served=True,
    status="wip",
    note=(
        "Claude Code CLI; omnigent's native driver on the gateway "
        "anthropic wire — launches but does not yet surface a scoreable "
        "run."
    ),
    install=INSTALL_CLAUDE,
)

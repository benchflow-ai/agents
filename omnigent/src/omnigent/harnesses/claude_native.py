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
    status="blocked",
    note=(
        "Claude Code CLI; omnigent's native driver launches the Claude "
        "TUI directly — omnigent 0.3.0 rejects the headless -p/--prompt "
        "flag for it ('REPL-only option(s) have no effect there'), so it "
        "cannot run one-shot benchmark turns. Use claude-sdk instead."
    ),
    install=INSTALL_CLAUDE,
)

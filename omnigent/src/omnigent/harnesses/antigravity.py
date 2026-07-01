"""BenchFlow agent spec for omnigent's ``antigravity`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="antigravity",
    harness_value="antigravity",
    wire="openai-chat",
    native=False,
    gateway_served=True,
    status="wip",
    note=(
        "Google Antigravity SDK (in-process); Gemini-native but routes "
        "generic traffic over the openai-compatible wire, so our openai "
        "provider IS applied — launches, not yet a scoreable run."
    ),
    install=None,
)

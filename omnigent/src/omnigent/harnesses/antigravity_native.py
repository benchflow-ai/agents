"""BenchFlow agent spec for omnigent's ``antigravity-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="antigravity-native",
    harness_value="antigravity-native",
    wire="vendor",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "Native Antigravity TUI bridge; consumes the gemini family "
        "(Gemini OAuth / GEMINI_API_KEY) the gateway does not provide."
    ),
    install=None,
)

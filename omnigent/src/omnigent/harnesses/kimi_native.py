"""BenchFlow agent spec for omnigent's ``kimi-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="kimi-native",
    harness_value="kimi-native",
    wire="vendor",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note="Kimi native TUI bridge; needs the kimi CLI + a Moonshot key.",
    install=None,
)

"""BenchFlow agent spec for omnigent's ``qwen-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="qwen-native",
    harness_value="qwen-native",
    wire="vendor",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "Qwen native TUI bridge; needs the qwen CLI + a vendor backend "
        "(provider not applied to the native variant)."
    ),
    install=None,
)

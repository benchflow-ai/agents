"""BenchFlow agent spec for omnigent's ``kiro-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="kiro-native",
    harness_value="kiro-native",
    wire="vendor",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "Kiro native TUI bridge (AWS Kiro proprietary wire); needs Kiro "
        "+ its backend (our gateway provider is not applied)."
    ),
    install=None,
)

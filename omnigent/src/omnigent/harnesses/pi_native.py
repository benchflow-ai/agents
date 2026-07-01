"""BenchFlow agent spec for omnigent's ``pi-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="pi-native",
    harness_value="pi-native",
    wire="pi-gateway",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "omnigent's native pi TUI bridge; not in omnigent's provider "
        "_HARNESS_FAMILY, so our gateway provider is not applied to it "
        "— needs pi's own backend."
    ),
    install=None,
)

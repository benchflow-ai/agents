"""BenchFlow agent spec for omnigent's ``goose-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="goose-native",
    harness_value="goose-native",
    wire="vendor",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note=("Goose native bridge; needs the goose binary + a vendor backend."),
    install=None,
)

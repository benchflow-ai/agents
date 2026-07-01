"""BenchFlow agent spec for omnigent's ``hermes-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="hermes-native",
    harness_value="hermes-native",
    wire="vendor",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note=("Hermes native TUI bridge; needs the hermes CLI + a vendor backend."),
    install=None,
)

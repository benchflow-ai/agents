"""BenchFlow agent spec for omnigent's ``hermes`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="hermes",
    harness_value="hermes",
    wire="vendor",
    native=False,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "Hermes headless subprocess; needs the hermes CLI + a vendor "
        "backend (our gateway provider is not applied)."
    ),
    install=None,
)

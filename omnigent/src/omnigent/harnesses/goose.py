"""BenchFlow agent spec for omnigent's ``goose`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="goose",
    harness_value="goose",
    wire="vendor",
    native=False,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "Block's Goose headless CLI (ACP); needs the goose binary + a "
        "vendor backend (our gateway provider is not applied)."
    ),
    install=None,
)

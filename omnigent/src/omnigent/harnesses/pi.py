"""BenchFlow agent spec for omnigent's ``pi`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="pi",
    harness_value="pi",
    wire="pi-gateway",
    native=False,
    gateway_served=True,
    status="worked",
    note=(
        "pi CLI (@earendil-works/pi-coding-agent) is in the base "
        "install; omnigent routes it to the gateway via its pi provider "
        "path (both families). Verified reward 1.0."
    ),
    install=None,
)

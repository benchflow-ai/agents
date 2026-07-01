"""BenchFlow agent spec for omnigent's ``copilot`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="copilot",
    harness_value="copilot",
    wire="vendor",
    native=False,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "GitHub Copilot SDK (bundles its binary); routes to the GitHub "
        "Copilot backend, not the gateway — needs a Copilot credential."
    ),
    install=None,
)

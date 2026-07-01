"""BenchFlow agent spec for omnigent's ``opencode-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="opencode-native",
    harness_value="opencode-native",
    wire="vendor",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "OpenCode native server bridge; needs the opencode binary + a "
        "vendor backend (our gateway provider is not applied)."
    ),
    install=None,
)

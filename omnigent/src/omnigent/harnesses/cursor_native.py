"""BenchFlow agent spec for omnigent's ``cursor-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="cursor-native",
    harness_value="cursor-native",
    wire="openai-chat",
    native=True,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "Cursor native terminal bridge; needs the cursor CLI + a vendor "
        "key (our gateway provider is not applied)."
    ),
    install=None,
)

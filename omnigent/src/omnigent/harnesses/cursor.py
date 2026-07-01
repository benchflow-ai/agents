"""BenchFlow agent spec for omnigent's ``cursor`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="cursor",
    harness_value="cursor",
    wire="openai-chat",
    native=False,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "Cursor headless CLI; speaks the openai-chat wire but is NOT in "
        "omnigent's provider _HARNESS_FAMILY, so our gateway provider "
        "is not applied — needs the cursor CLI + a vendor key."
    ),
    install=None,
)

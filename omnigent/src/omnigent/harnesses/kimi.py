"""BenchFlow agent spec for omnigent's ``kimi`` harness."""

from __future__ import annotations

from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="kimi",
    harness_value="kimi",
    wire="vendor",
    native=False,
    gateway_served=False,
    status="needs-vendor",
    note=(
        "Moonshot Kimi Code CLI; intentionally absent from omnigent's "
        "provider routing (no per-spawn override — config lives in "
        "~/.kimi/config.toml). Needs the kimi CLI + a Moonshot key."
    ),
    install=None,
)

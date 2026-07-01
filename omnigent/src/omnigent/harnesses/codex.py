"""BenchFlow agent spec for omnigent's ``codex`` harness."""

from __future__ import annotations

from omnigent.harnesses._installers import INSTALL_CODEX
from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="codex",
    harness_value="codex",
    wire="openai-responses",
    native=False,
    gateway_served=True,
    status="blocked",
    note=(
        "codex CLI (@openai/codex); our openai provider is applied, but "
        "codex speaks the openai Responses wire and the gateway serves "
        "no /v1/responses → api_error. Unblocks via benchflow-core "
        "(#38)."
    ),
    install=INSTALL_CODEX,
)

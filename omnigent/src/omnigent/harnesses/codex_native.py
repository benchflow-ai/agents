"""BenchFlow agent spec for omnigent's ``codex-native`` harness."""

from __future__ import annotations

from omnigent.harnesses._installers import INSTALL_CODEX
from omnigent.harnesses._spec import HarnessSpec

SPEC = HarnessSpec(
    slug="codex-native",
    harness_value="codex-native",
    wire="openai-responses",
    native=True,
    gateway_served=True,
    status="blocked",
    note=(
        "codex CLI; omnigent's native codex driver — same "
        "Responses-wire blocker as codex (no gateway /v1/responses)."
    ),
    install=INSTALL_CODEX,
)

"""The omnigent harness registry — BenchFlow's single source of truth.

One ``<harness_value>.py`` module per harness (mirroring omnigent's own
``inner/*_harness.py`` layout), each exposing a ``SPEC``. This collector imports
them in canonical order — the analog of omnigent's
``runtime.harnesses._HARNESS_MODULES`` — and exposes:

* :data:`HARNESS_SPECS` — the ordered tuple of all specs.
* :data:`HARNESS_SPECS_BY_SLUG` — lookup by BenchFlow slug.

``register.py`` and ``agent.py`` DERIVE everything (the ``HARNESSES`` table, the
per-harness status/install maps, and the ``build_omnigent_<slug>`` factories)
from this registry, so adding/removing a harness is a one-file change here.
Aliases + the native set live in :mod:`omnigent.harnesses._aliases` (a mirror of
omnigent's ``harness_aliases.py``).
"""

from __future__ import annotations

from omnigent.harnesses import (
    antigravity,
    antigravity_native,
    claude_native,
    claude_sdk,
    codex,
    codex_native,
    copilot,
    cursor,
    cursor_native,
    goose,
    goose_native,
    hermes,
    hermes_native,
    kimi,
    kimi_native,
    kiro_native,
    openai_agents,
    opencode_native,
    pi,
    pi_native,
    qwen,
    qwen_native,
)
from omnigent.harnesses._spec import HarnessSpec

# Canonical order: SDK harness then its native twin, grouped by vendor — matches
# how omnigent groups them in _HARNESS_MODULES.
HARNESS_SPECS: tuple[HarnessSpec, ...] = (
    pi.SPEC,
    pi_native.SPEC,
    claude_sdk.SPEC,
    claude_native.SPEC,
    codex.SPEC,
    codex_native.SPEC,
    openai_agents.SPEC,
    cursor.SPEC,
    cursor_native.SPEC,
    kimi.SPEC,
    kimi_native.SPEC,
    qwen.SPEC,
    qwen_native.SPEC,
    goose.SPEC,
    goose_native.SPEC,
    hermes.SPEC,
    hermes_native.SPEC,
    antigravity.SPEC,
    antigravity_native.SPEC,
    copilot.SPEC,
    kiro_native.SPEC,
    opencode_native.SPEC,
)

HARNESS_SPECS_BY_SLUG: dict[str, HarnessSpec] = {s.slug: s for s in HARNESS_SPECS}

__all__ = ["HarnessSpec", "HARNESS_SPECS", "HARNESS_SPECS_BY_SLUG"]

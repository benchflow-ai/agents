"""The harness spec registry is BenchFlow's single source of truth.

These guard the invariants everything downstream derives from: the exact set of
omnigent 0.3.0 harnesses, the per-harness ``build_omnigent_*`` factories, that
``register.py`` stays a pure derivation (no hand-maintained copy creeps back),
the native/alias mirror of omnigent's ``harness_aliases.py``, and the
``gateway_served`` classification against omnigent's provider ``_HARNESS_FAMILY``.
"""

from omnigent import agent as agent_mod
from omnigent.harnesses import HARNESS_SPECS, HARNESS_SPECS_BY_SLUG
from omnigent.harnesses._aliases import (
    NATIVE_HARNESSES,
    canonicalize_harness,
    is_native_harness,
)
from omnigent.session import _is_startup_race

# The 22 canonical ``--harness`` values omnigent 0.3.0 dispatches (its
# _HARNESS_MODULES, aliases folded). Hard-coded so dropping/adding a spec fails.
_CANONICAL_22 = {
    "pi",
    "pi-native",
    "claude-sdk",
    "claude-native",
    "codex",
    "codex-native",
    "openai-agents",
    "cursor",
    "cursor-native",
    "kimi",
    "kimi-native",
    "qwen",
    "qwen-native",
    "goose",
    "goose-native",
    "hermes",
    "hermes-native",
    "antigravity",
    "antigravity-native",
    "copilot",
    "kiro-native",
    "opencode-native",
}

# omnigent applies OUR openai/anthropic gateway provider only to these (its
# provider_config._HARNESS_FAMILY openai/anthropic entries, plus ``pi`` via
# _apply_provider_to_pi). Everything else falls back to a vendor backend.
_GATEWAY_SERVED = {
    "pi",
    "claude-sdk",
    "claude-native",
    "codex",
    "codex-native",
    "openai-agents",
    "antigravity",
    "qwen",
}


def test_specs_are_exactly_the_22_canonical_values() -> None:
    values = [s.harness_value for s in HARNESS_SPECS]
    assert set(values) == _CANONICAL_22
    assert len(values) == 22
    assert len(set(values)) == 22, "duplicate harness_value"
    assert len({s.slug for s in HARNESS_SPECS}) == 22, "duplicate slug"


def test_every_spec_has_a_bound_factory() -> None:
    """The module-level ``build_omnigent_<slug>`` globals are generated for all
    22 specs and each binds its harness_value."""
    for s in HARNESS_SPECS:
        fname = f"build_omnigent_{s.slug.replace('-', '_')}"
        factory = getattr(agent_mod, fname)
        assert factory()._harness == s.harness_value


def test_register_tables_are_pure_derivations() -> None:
    """register.py must DERIVE its tables from HARNESS_SPECS — guards against a
    hand-maintained copy drifting from the registry."""
    import sys

    import omnigent  # noqa: F401  (import side effect registers + loads submodule)

    r = sys.modules["omnigent.register"]
    assert r.HARNESSES == [(s.slug, s.harness_value, s.note) for s in HARNESS_SPECS]
    assert r._HARNESS_STATUS == {s.slug: s.status for s in HARNESS_SPECS}
    assert r._HARNESS_SETUP == {s.slug: s.install for s in HARNESS_SPECS if s.install}


def test_native_flag_mirrors_omnigent_native_set() -> None:
    """``native`` is True exactly for omnigent's native harnesses (its
    NATIVE_HARNESSES mirror) — and every native value ends ``-native``."""
    for s in HARNESS_SPECS:
        assert s.native == (s.harness_value in NATIVE_HARNESSES)
        assert s.native == is_native_harness(s.harness_value)
        if s.native:
            assert s.harness_value.endswith("-native")


def test_alias_mirror_spot_checks() -> None:
    """The vendored harness_aliases mirror resolves the canonical aliases."""
    assert canonicalize_harness("claude") == "claude-sdk"
    assert canonicalize_harness("openai-agents-sdk") == "openai-agents"
    assert canonicalize_harness("opencode") == "opencode-native"
    assert canonicalize_harness("kimi-code") == "kimi"
    assert canonicalize_harness("github-copilot") == "copilot"
    # unknown names pass through unchanged.
    assert canonicalize_harness("nope") == "nope"


def test_gateway_served_matches_provider_family() -> None:
    """``gateway_served`` is True exactly for the harnesses omnigent applies our
    openai/anthropic provider to (its _HARNESS_FAMILY ∪ {pi}). This encodes the
    honest 'runs on the gateway vs needs-vendor' split."""
    served = {s.harness_value for s in HARNESS_SPECS if s.gateway_served}
    assert served == _GATEWAY_SERVED
    # a not-served harness must be blocked / wip / needs-vendor, never worked/runs.
    for s in HARNESS_SPECS:
        if not s.gateway_served:
            assert s.status in {"needs-vendor", "wip", "blocked"}


def test_status_values_are_from_the_known_vocabulary() -> None:
    allowed = {"worked", "runs", "blocked", "wip", "needs-vendor"}
    assert {s.status for s in HARNESS_SPECS} <= allowed


def test_only_cli_harnesses_carry_an_install_snippet() -> None:
    """Only the codex/claude families auto-install a vendor CLI; every other
    harness relies on the base install (pi / bundled SDK) or is needs-vendor."""
    with_install = {s.slug for s in HARNESS_SPECS if s.install}
    assert with_install == {"claude", "claude-native", "codex", "codex-native"}


def test_by_slug_lookup_is_complete() -> None:
    assert set(HARNESS_SPECS_BY_SLUG) == {s.slug for s in HARNESS_SPECS}


def test_is_startup_race_matches_only_startup_markers() -> None:
    """The retry gate fires on the daemon/server startup race, never on a real
    agent failure."""
    assert _is_startup_race(
        "The local daemon exited before its Omnigent server became ready.", ""
    )
    assert _is_startup_race(
        "", "Timed out after 60s waiting for the local Omnigent server"
    )
    # a genuine agent/tool error is NOT a startup race → not retried.
    assert not _is_startup_race("Traceback: ValueError in tool call", "exit 1")
    assert not _is_startup_race("", "")

"""Registration + pure-helper tests for the Omnigent BenchFlow agents.

The pure helpers (``_normalize_base_url`` / ``_build_config_yaml``) and the
``install_cmd`` content are import-safe and run on any benchflow. The full
registration assertions gate on the session-factory seam: on a benchflow whose
``VALID_PROTOCOLS`` lacks ``"session-factory"`` (e.g. published 0.6.x),
``register()`` returns ``None`` by design and those tests skip.

Scope: the package now lists ALL 22 canonical Omnigent harnesses (one
``omnigent-<slug>`` per ``HARNESSES`` entry — the full upstream set incl. the
``*-native`` drivers). Only ``omnigent-pi`` is fully worked; the rest are
listed-not-wired (honest status in each ``description``).
"""

import pytest

from omnigent import agent as agent_mod
from omnigent.agent import _build_config_yaml, _normalize_base_url
from omnigent.register import (
    HARNESSES,
    OMNIGENT_INSTALL_CMD,
    OMNIGENT_PIN,
    register,
)


def _seam_present() -> bool:
    try:
        from benchflow.agents.registry import VALID_PROTOCOLS
    except Exception:
        return False
    return "session-factory" in VALID_PROTOCOLS


# ── Pure helpers (no seam, no sandbox runtime) ────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/v1/", "https://api.deepseek.com/v1"),
        ("", ""),
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    assert _normalize_base_url(raw) == expected


def test_build_config_yaml_quotes_and_shape() -> None:
    yaml = _build_config_yaml(
        base_url="https://api.deepseek.com/v1",
        api_key='sk-"weird"\\key',
        model="deepseek-chat",
    )
    assert "kind: gateway" in yaml
    assert "wire_api: chat" in yaml
    # scalar values are double-quoted (the model lands under models.default).
    assert 'default: "deepseek-chat"' in yaml
    assert 'base_url: "https://api.deepseek.com/v1"' in yaml
    # YAML-special chars in the key are escaped inside double quotes.
    assert '\\"weird\\"' in yaml and "\\\\key" in yaml


# ── install_cmd content (import-safe) ─────────────────────────────────────


def test_install_cmd_has_node_on_bare_path_and_tmux() -> None:
    cmd = OMNIGENT_INSTALL_CMD
    # node/npm/npx symlinked onto the bare PATH (pi is a node-shebang script).
    assert "for _b in node npm npx" in cmd
    # tmux installed (managed REPL terminal needs it).
    assert "tmux" in cmd
    # final verify covers the whole toolchain.
    assert "which pi" in cmd and "which node" in cmd and "which tmux" in cmd
    # pinned omnigent + pinned python.
    assert f"omnigent=={OMNIGENT_PIN}" in cmd and "--python 3.12" in cmd


def test_run_timeout_backstop_is_generous() -> None:
    """The sandbox-exec backstop must sit ABOVE typical task budgets (600-900s)
    so it never clips a legitimate long turn — the kernel's wait_for on the
    task's own ``[agent] timeout_sec`` is the authoritative per-turn bound. A
    once-hardcoded 600 clipped tasks with a 900s budget; default is now 1800,
    overridable via BENCHFLOW_OMNIGENT_RUN_TIMEOUT_SEC.
    """
    from omnigent.session import _RUN_TIMEOUT_SEC

    assert _RUN_TIMEOUT_SEC >= 900


# ── Harness table + per-harness factories (no seam) ───────────────────────


def test_harness_table_covers_all_canonical_harnesses() -> None:
    """All 22 canonical Omnigent harnesses (upstream omnigent/inner/*_harness.py),
    each mapped to its canonical ``--harness`` value (aliases resolved, e.g.
    opencode→opencode-native, claude→claude-sdk)."""
    by_slug = {slug: value for slug, value, _note in HARNESSES}
    assert by_slug == {
        # vendor SDK / CLI harnesses
        "pi": "pi",
        "claude": "claude-sdk",
        "codex": "codex",
        "cursor": "cursor",
        "opencode": "opencode-native",
        "hermes": "hermes",
        "openai-agents": "openai-agents",
        "goose": "goose",
        "qwen": "qwen",
        "kimi": "kimi",
        "copilot": "copilot",
        "antigravity": "antigravity",
        # omnigent native drivers
        "pi-native": "pi-native",
        "claude-native": "claude-native",
        "codex-native": "codex-native",
        "cursor-native": "cursor-native",
        "hermes-native": "hermes-native",
        "goose-native": "goose-native",
        "qwen-native": "qwen-native",
        "kimi-native": "kimi-native",
        "antigravity-native": "antigravity-native",
        "kiro-native": "kiro-native",
    }


def test_per_harness_factories_are_module_globals_with_right_harness() -> None:
    """Each ``omnigent.agent:build_omnigent_<slug>`` resolves and binds its
    harness; the function carries a correct ``__name__``/``__qualname__``."""
    for slug, value, _note in HARNESSES:
        fname = f"build_omnigent_{slug.replace('-', '_')}"
        factory = getattr(agent_mod, fname)
        assert factory.__name__ == fname
        assert factory.__qualname__ == fname
        built = factory()
        assert built._harness == value


def test_build_omnigent_agent_back_compat_defaults_to_pi() -> None:
    """The generic alias is retained and still builds a ``pi`` agent."""
    assert agent_mod.build_omnigent_agent()._harness == "pi"
    # exec_user override still flows through.
    assert agent_mod.build_omnigent_agent(exec_user="me")._exec_user == "me"


# ── Full registration (gated on the session-factory seam) ─────────────────


def test_seam_detection_matches_valid_protocols() -> None:
    """The package's seam probe agrees with the helper used by these tests."""
    from omnigent.register import _session_factory_seam_present

    assert _session_factory_seam_present() == _seam_present()


def test_register_returns_none_when_seam_absent(monkeypatch) -> None:
    """Degradation path — version-independent: force the seam absent and assert
    ``register()`` declines (returns None) rather than registering
    non-connectable agents. Published BenchFlow does not validate ``protocol`` at
    registration time, so the up-front gate (not a register_agent exception) is
    what guarantees this.
    """
    import sys

    import omnigent.register  # noqa: F401  (ensure the submodule is in sys.modules)

    # NB: the `omnigent` package attribute `register` is the *function*
    # (re-exported by __init__), which shadows the submodule — so fetch the real
    # module from sys.modules to patch its module-level helper.
    register_mod = sys.modules["omnigent.register"]
    monkeypatch.setattr(register_mod, "_session_factory_seam_present", lambda: False)
    assert register_mod.register() is None


def test_register_wires_all_harnesses_with_seam() -> None:
    if not _seam_present():
        pytest.skip("benchflow build lacks the session-factory seam")
    from benchflow.agents.registry import resolve_agent

    configs = register()
    assert configs is not None
    by_name = {c.name: c for c in configs}
    # every harness in the table registered, named omnigent-<slug>.
    assert set(by_name) == {f"omnigent-{slug}" for slug, _v, _n in HARNESSES}

    for slug, _value, _note in HARNESSES:
        name = f"omnigent-{slug}"
        cfg = by_name[name]
        assert cfg.protocol == "session-factory"
        expected_factory = f"omnigent.agent:build_omnigent_{slug.replace('-', '_')}"
        assert cfg.session_factory == expected_factory
        # resolvable by name through the public registry.
        assert resolve_agent(name).session_factory == expected_factory


def test_register_includes_pi_and_claude_with_seam() -> None:
    """Spot-check the worked agent + a listed one (the task's minimum)."""
    if not _seam_present():
        pytest.skip("benchflow build lacks the session-factory seam")

    by_name = {c.name: c for c in register()}
    assert "omnigent-pi" in by_name and "omnigent-claude" in by_name

    # pi is the fully-worked one — no listed-not-wired caveat in its blurb.
    assert "STATUS: listed" not in by_name["omnigent-pi"].description
    assert by_name["omnigent-pi"].launch_cmd == "omnigent run --harness pi"

    # claude is listed-not-wired and honest about it (claude-sdk harness value).
    claude = by_name["omnigent-claude"]
    assert claude.launch_cmd == "omnigent run --harness claude-sdk"
    assert "STATUS: listed" in claude.description
    assert "not yet wired" in claude.description
    # all harnesses reuse the shared install_cmd.
    assert claude.install_cmd == OMNIGENT_INSTALL_CMD

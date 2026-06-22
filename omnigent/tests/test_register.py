"""Registration + pure-helper tests for the Omnigent BenchFlow agent.

The pure helpers (``_normalize_base_url`` / ``_build_config_yaml``) and the
``install_cmd`` content are import-safe and run on any benchflow. The full
registration assertions gate on the session-factory seam: on a benchflow whose
``VALID_PROTOCOLS`` lacks ``"session-factory"`` (e.g. published 0.6.x),
``register()`` returns ``None`` by design and those tests skip.
"""

import pytest

from omnigent.agent import _build_config_yaml, _normalize_base_url
from omnigent.register import (
    OMNIGENT_PIN,
    OMNIGENT_SESSION_FACTORY,
    OMNIGENT_INSTALL_CMD,
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


def test_session_factory_points_into_this_package() -> None:
    assert OMNIGENT_SESSION_FACTORY == "omnigent.agent:build_omnigent_agent"


def test_run_timeout_backstop_is_generous() -> None:
    """The sandbox-exec backstop must sit ABOVE typical task budgets (600-900s)
    so it never clips a legitimate long turn — the kernel's wait_for on the
    task's own ``[agent] timeout_sec`` is the authoritative per-turn bound. A
    once-hardcoded 600 clipped tasks with a 900s budget; default is now 1800,
    overridable via BENCHFLOW_OMNIGENT_RUN_TIMEOUT_SEC.
    """
    from omnigent.session import _RUN_TIMEOUT_SEC

    assert _RUN_TIMEOUT_SEC >= 900


# ── Full registration (gated on the session-factory seam) ─────────────────


def test_seam_detection_matches_valid_protocols() -> None:
    """The package's seam probe agrees with the helper used by these tests."""
    from omnigent.register import _session_factory_seam_present

    assert _session_factory_seam_present() == _seam_present()


def test_register_returns_none_when_seam_absent(monkeypatch) -> None:
    """Degradation path — version-independent: force the seam absent and assert
    ``register()`` declines (returns None) rather than registering a
    non-connectable agent. Published BenchFlow does not validate ``protocol`` at
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


def test_register_wires_session_factory_with_seam() -> None:
    if not _seam_present():
        pytest.skip("benchflow build lacks the session-factory seam")
    from benchflow.agents.registry import resolve_agent

    config = register()
    assert config is not None
    assert config.name == "omnigent-pi"
    assert config.protocol == "session-factory"
    assert config.session_factory == OMNIGENT_SESSION_FACTORY
    # resolvable by name through the public registry.
    assert resolve_agent("omnigent-pi").session_factory == OMNIGENT_SESSION_FACTORY
    # pi skill-discovery dirs registered so the with/without-skills axis is real
    # (core deploy_skills symlinks /skills into these only when skill_paths is set).
    assert config.skill_paths == [
        "$HOME/.pi/agent/skills",
        "$HOME/.agents/skills",
    ]

"""Registration + overlay-content tests for the ``omnigent-mimo`` agent.

Like :mod:`test_register`, the import-safe assertions (install-cmd content, the
overlay-source invariants, the session-factory pointer) run on any benchflow; the
full registration assertions gate on the session-factory seam and skip on a
benchflow whose ``VALID_PROTOCOLS`` lacks ``"session-factory"``.
"""

import pytest

from omnigent.agent import _build_mimo_env_file, build_omnigent_mimo_agent
from omnigent.register import (
    MIMO_INSTALL_CMD,
    OMNIGENT_MIMO_SESSION_FACTORY,
    OMNIGENT_PIN,
    register_mimo,
)


def _seam_present() -> bool:
    try:
        from benchflow.agents.registry import VALID_PROTOCOLS
    except Exception:
        return False
    return "session-factory" in VALID_PROTOCOLS


# ── session-factory pointer + agent factory ───────────────────────────────


def test_mimo_session_factory_points_into_this_package():
    assert OMNIGENT_MIMO_SESSION_FACTORY == "omnigent.agent:build_omnigent_mimo_agent"


def test_build_mimo_agent_pins_harness():
    agent = build_omnigent_mimo_agent()
    assert agent._harness == "mimo"
    # explicit override still wins (test ergonomics)
    assert build_omnigent_mimo_agent(harness="pi")._harness == "pi"


# ── mimo.env rendering (secret-safe cred passing) ─────────────────────────


def test_mimo_env_file_keyless_is_comment_only():
    env = _build_mimo_env_file(base_url="", api_key="")
    assert "HARNESS_MIMO_GATEWAY_API_KEY" not in env
    assert "HARNESS_MIMO_GATEWAY_BASE_URL" not in env
    assert env.strip().startswith("#")  # sourcing it is a clean no-op


def test_mimo_env_file_exports_and_quotes():
    env = _build_mimo_env_file(base_url="https://x/v1", api_key="sk-'weird")
    assert "export HARNESS_MIMO_GATEWAY_BASE_URL='https://x/v1'" in env
    # single-quote inside the key is escaped so it can't break the shell file
    assert "HARNESS_MIMO_GATEWAY_API_KEY='sk-'\\''weird'" in env


# ── install_cmd content (import-safe) ─────────────────────────────────────


def test_install_cmd_installs_omnigent_and_mimo_cli_not_pi():
    cmd = MIMO_INSTALL_CMD
    assert f"omnigent=={OMNIGENT_PIN}" in cmd and "--python 3.12" in cmd
    assert "@mimo-ai/cli@0.1.1" in cmd
    # this is the MiMo overlay, not the pi harness
    assert "@earendil-works/pi-coding-agent" not in cmd
    assert "for _b in node npm npx" in cmd and "tmux" in cmd


def test_install_cmd_uses_copy_link_mode_to_avoid_cache_poisoning():
    # uv hardlinks package files from its cache by default; the overlay appends to
    # installed modules, which would mutate the shared cache inode and poison every
    # later install. --link-mode=copy gives private file copies. (Caught live: an
    # append-poisoned cache survived `--force` reinstall with a broken module.)
    assert "--link-mode=copy" in MIMO_INSTALL_CMD


def test_install_cmd_deploys_all_three_overlay_modules():
    cmd = MIMO_INSTALL_CMD
    for name in ("_mimo_acp.py", "mimo_executor.py", "mimo_harness.py"):
        assert f'base64 -d > "$OMNI_PKG/inner/{name}"' in cmd


def test_install_cmd_registers_mimo_in_all_three_registries():
    cmd = MIMO_INSTALL_CMD
    # _HARNESS_MODULES dispatch + OMNIGENT_HARNESSES validation gate + the
    # model-override allowlist, all appended to the installed omnigent modules.
    assert '_HARNESS_MODULES["mimo"] = "omnigent.inner.mimo_harness"' in cmd
    assert 'OMNIGENT_HARNESSES = OMNIGENT_HARNESSES | frozenset({"mimo"})' in cmd
    assert (
        '_SDK_MODEL_OVERRIDE_HARNESSES = _SDK_MODEL_OVERRIDE_HARNESSES | frozenset({"mimo"})'
        in cmd
    )
    assert "runtime/harnesses/__init__.py" in cmd
    assert "spec/_omnigent_compat.py" in cmd
    assert "model_override.py" in cmd


def test_install_cmd_asserts_registration_took():
    cmd = MIMO_INSTALL_CMD
    # The install must fail loudly if omnigent's internals drifted under the pin:
    # all registries are asserted AND the harness module is import-checked. (The
    # verify snippet is shlex-quoted into one shell arg, so assert on the tokens
    # that survive single-quote escaping, not the raw ``'mimo'`` literal.)
    assert "in OMNIGENT_HARNESSES" in cmd
    assert "_HARNESS_MODULES.get(" in cmd
    assert "harness_supports_model_override(" in cmd
    assert "import_module(" in cmd and "omnigent.inner.mimo_harness" in cmd
    assert "which mimo" in cmd


# ── overlay source invariants (the deployed modules) ──────────────────────


def _overlay_source(name: str) -> str:
    from pathlib import Path

    import omnigent

    return (Path(omnigent.__file__).parent / "overlay" / name).read_text()


def test_overlay_executor_is_faithful_mimo_acp_not_serve():
    src = _overlay_source("mimo_executor.py")
    # drives MiMo's native ACP loop (the proven Workstream-A transport) ...
    assert "MimoAcp" in src and "run_prompt" in src
    # ... handles its own tools (Session must not re-execute) ...
    assert "def handles_tools_internally" in src and "return True" in src
    # ... and is a real Omnigent Executor yielding the Executor event vocabulary.
    assert "class MimoExecutor(Executor)" in src
    assert "TurnComplete" in src and "ToolCallRequest" in src


def test_overlay_executor_writes_trackability_trace():
    # MiMo runs usage_tracking=off, so the executor must persist the turn's tool
    # calls + native usage for OmnigentSession to surface (else reward is nulled).
    src = _overlay_source("mimo_executor.py")
    assert "trace_path" in src and "_write_trace" in src
    assert '"tools"' in src and '"usage"' in src  # the producer↔consumer contract


def test_overlay_harness_exposes_create_app_over_adapter():
    src = _overlay_source("mimo_harness.py")
    assert "def create_app() -> FastAPI" in src
    assert "ExecutorAdapter(executor_factory=_build_mimo_executor)" in src
    # reads the model + the trackability trace path from the HARNESS_MIMO_* env
    assert "HARNESS_MIMO_MODEL" in src and "HARNESS_MIMO_TRACE" in src


def test_overlay_acp_bridge_is_dependency_free():
    src = _overlay_source("_mimo_acp.py")
    # the pure bridge must not IMPORT omnigent/fastapi so it stays unit-testable
    # (the words appear in the module docstring; assert on import statements).
    assert "import fastapi" not in src and "from fastapi" not in src
    assert "import omnigent" not in src and "from omnigent" not in src
    assert 'DEFAULT_MODEL = "mimo/mimo-auto"' in src


# ── full registration (gated on the session-factory seam) ─────────────────


def test_register_mimo_returns_none_when_seam_absent(monkeypatch):
    import sys

    import omnigent.register  # noqa: F401

    register_mod = sys.modules["omnigent.register"]
    monkeypatch.setattr(register_mod, "_session_factory_seam_present", lambda: False)
    assert register_mod.register_mimo() is None


def test_register_mimo_wires_session_factory_with_seam():
    if not _seam_present():
        pytest.skip("benchflow build lacks the session-factory seam")
    from benchflow.agents.registry import resolve_agent

    config = register_mimo()
    assert config is not None
    assert config.name == "omnigent-mimo"
    assert config.protocol == "session-factory"
    assert config.session_factory == OMNIGENT_MIMO_SESSION_FACTORY
    assert (
        resolve_agent("omnigent-mimo").session_factory == OMNIGENT_MIMO_SESSION_FACTORY
    )

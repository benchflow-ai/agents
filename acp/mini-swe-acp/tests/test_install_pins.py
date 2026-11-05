"""The sandbox install is pinned and checks the path every model call takes.

Regression for LiteLLM 1.106.0: an unpinned ``pip install mini-swe-agent``
picked it up on 2026-10-18, and its ``completion()`` imports ``mcp`` whenever
tools are passed, so every trial failed in its model calls after a clean
install. Needs ``benchflow`` (register.py imports its registry helpers).
"""

import base64
import importlib
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("benchflow")

# The package exports the register() function under the module's name.
register = importlib.import_module("mini_swe_acp.register")

_REQUIREMENTS = Path(register.__file__).with_name("requirements.txt")
_PIN = re.compile(r"^[A-Za-z0-9._-]+==[A-Za-z0-9.+_-]+( ; .+)?$")


def _requirement_lines() -> list[str]:
    return [
        line
        for line in _REQUIREMENTS.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_every_requirement_is_an_exact_pin():
    lines = _requirement_lines()
    assert lines
    assert [line for line in lines if not _PIN.match(line)] == []
    assert f"mini-swe-agent=={register.MINI_SWE_AGENT_VERSION}" in lines
    assert f"litellm=={register.LITELLM_VERSION}" in lines


def test_install_writes_the_pinned_list_and_installs_only_it():
    cmd = register._install_cmd()
    encoded = re.search(
        rf"echo (\S+) \| base64 -d > {re.escape(register._REQUIREMENTS_PATH)}", cmd
    )
    assert encoded, cmd
    assert base64.b64decode(encoded.group(1)).decode() == _REQUIREMENTS.read_text()
    assert f"pip --isolated install -q -r {register._REQUIREMENTS_PATH}" in cmd
    assert (
        f"pip install -q --python {register._MINI_SWE_VENV}/bin/python pip=={register.PIP_VERSION}"
        in cmd
    )
    # No bare, unversioned install of the agent or of LiteLLM is left.
    assert not re.search(
        r"pip install( -q)?( --upgrade)? (mini-swe-agent|litellm)\b", cmd
    )
    assert "--upgrade pip" not in cmd


def test_install_ends_with_a_tool_call_probe():
    cmd = register._install_cmd()
    probe = cmd.rsplit("&& ", 1)[-1]
    assert "litellm.completion(" in probe
    assert "tools=[" in probe
    assert "mock_response='ok'" in probe
    assert "LITELLM_LOCAL_MODEL_COST_MAP=True" in probe
    compile(register._TOOL_CALL_PROBE, "<probe>", "exec")


def test_the_pinned_install_is_offered_for_caching_when_benchflow_can(monkeypatch):
    def new_register_agent(name, install_cmd, launch_cmd, *, cacheable_version=""):
        return None

    def old_register_agent(name, install_cmd, launch_cmd):
        return None

    monkeypatch.setattr(register, "register_agent", new_register_agent)
    assert register._cache_kwargs() == {
        "cacheable_version": (
            f"{register.MINI_SWE_AGENT_VERSION}+litellm-{register.LITELLM_VERSION}"
            f"+private-python-{register.PYTHON_VERSION}-uv-{register.UV_VERSION}-v1"
        )
    }
    monkeypatch.setattr(register, "register_agent", old_register_agent)
    assert register._cache_kwargs() == {}


def test_private_runtime_never_installs_task_system_packages():
    """Guards PY8-D1000 / agents PR #80's system-Python regression."""
    cmd = register._install_cmd()
    for forbidden in (
        "apt-get",
        "apk add",
        "dnf ",
        "yum ",
        "python3 -m venv",
        "export PATH=",
    ):
        assert forbidden not in cmd
    assert "--no-bin --reinstall 3.12.15" in cmd
    assert "UV_PYTHON_PREFERENCE=only-managed" in cmd
    root = register.RUNTIME_ROOT
    assert register._launch_cmd().endswith(
        f"{root}/mini-swe-venv/bin/python {root}/bin/mini-swe-acp-shim"
    )


def test_installs_under_the_runtime_root_benchflow_gives():
    """The venv, its requirements and uv's temp folder sit in BenchFlow's
    runtime tree, wherever this BenchFlow keeps it. BenchFlow moved the tree
    from /opt/benchflow to /opt/runtime and stopped making /opt/benchflow, so
    a venv left there sat under a folder the private temp folder's umask 077
    made: one only root could enter, and the agent's user got Permission
    denied running it."""
    from benchflow._runtime_tree import RUNTIME_ROOT

    assert register.RUNTIME_ROOT == RUNTIME_ROOT
    cmd = register._install_cmd()
    for name in ("mini-swe-venv", "mini-swe-requirements.txt", "mini-swe-tmp"):
        assert f"{RUNTIME_ROOT}/{name}" in cmd
    if RUNTIME_ROOT != "/opt/benchflow":
        assert "/opt/benchflow" not in cmd + register._launch_cmd()


def test_a_benchflow_without_the_runtime_tree_keeps_the_old_root(monkeypatch):
    """Without ``benchflow._runtime_tree`` the install keeps /opt/benchflow."""
    monkeypatch.setitem(sys.modules, "benchflow._runtime_tree", None)
    try:
        old = importlib.reload(register)
        assert old.RUNTIME_ROOT == "/opt/benchflow"
        assert old._MINI_SWE_VENV == "/opt/benchflow/mini-swe-venv"
        assert old._REQUIREMENTS_PATH == "/opt/benchflow/mini-swe-requirements.txt"
    finally:
        monkeypatch.undo()
        importlib.reload(register)

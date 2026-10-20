"""The sandbox install is pinned and checks the path every model call takes.

Regression for LiteLLM 1.106.0: an unpinned ``pip install mini-swe-agent``
picked it up on 2026-10-18, and its ``completion()`` imports ``mcp`` whenever
tools are passed, so every trial failed in its model calls after a clean
install. Needs ``benchflow`` (register.py imports its registry helpers).
"""

import base64
import importlib
import re
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
        r"echo (\S+) \| base64 -d > /opt/benchflow/mini-swe-requirements\.txt", cmd
    )
    assert encoded, cmd
    assert base64.b64decode(encoded.group(1)).decode() == _REQUIREMENTS.read_text()
    assert "pip install -q -r /opt/benchflow/mini-swe-requirements.txt" in cmd
    assert f"pip install -q pip=={register.PIP_VERSION}" in cmd
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

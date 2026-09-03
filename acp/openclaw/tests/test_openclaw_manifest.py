"""OpenClaw-specific active manifest contract."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_MANIFEST = Path(__file__).resolve().parents[1] / "manifest.toml"


def test_benchflow_runtime_fields() -> None:
    """Guards BenchFlow PR #1090 manifest-owned runtime configuration."""
    manifest = tomllib.loads(_MANIFEST.read_text())
    assert manifest.get("default_model", "") == ""
    assert manifest.get("requires_env", []) == []
    assert manifest["home_dirs"] == [".openclaw"]
    assert "$WORKSPACE/skills" in manifest["skill_paths"]


def test_runtime_and_node_versions_are_exactly_pinned() -> None:
    """Guards BenchFlow PR #704's compatible OpenClaw and Node pins."""
    install_cmd = tomllib.loads(_MANIFEST.read_text())["install_cmd"]
    assert re.findall(r"\bopenclaw@[^ )]+", install_cmd) == ["openclaw@2026.6.9"]
    assert re.findall(r"\bBF_NODE_VERSION=[^; ]+", install_cmd) == [
        "BF_NODE_VERSION=22.20.0"
    ]

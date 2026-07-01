"""The pyproject's benchflow.agents entry point resolves.

Guards drift: a module rename would otherwise fail only as a silent runtime
warning inside benchflow's plugin autoload. Parses this package's own
pyproject (not installed metadata) so it works in per-package CI.
"""

import importlib
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_benchflow_agents_entry_point_resolves():
    eps = tomllib.loads(_PYPROJECT.read_text())["project"]["entry-points"][
        "benchflow.agents"
    ]
    assert eps, "benchflow.agents entry point disappeared from pyproject"
    for value in eps.values():
        mod, _, attr = value.partition(":")
        obj = importlib.import_module(mod)
        if attr:
            assert callable(getattr(obj, attr))

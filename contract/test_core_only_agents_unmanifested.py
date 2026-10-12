"""benchflow core agents that must not get a manifest here, by name or alias.

antigravity depends on core-only settings (its web-tool and hosted-search
policy, MCP config path and ACP effort option) that a data-only manifest
cannot carry. Released benchflow 0.7.x has no core entry for it and
auto-loads unknown agents from this repo's main, so a manifest would give
those users antigravity without that policy: a "no web" run would keep its
server-side web search. benchflow's manifest-parity test holds the same rule."""

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SKIP = {".git", "node_modules", "dist", "build", ".venv", "__pycache__"}
FORBIDDEN_NAMES = {"antigravity"}
FORBIDDEN_ALIASES = {"antigravity", "agy"}


def test_core_only_agents_have_no_manifest():
    hits = []
    for f in REPO.rglob("manifest.toml"):
        if any(part in _SKIP for part in f.relative_to(REPO).parts):
            continue
        data = tomllib.loads(f.read_text())
        if data.get("name") in FORBIDDEN_NAMES:
            hits.append(f"{f.relative_to(REPO)}: name {data['name']!r}")
        for alias in data.get("aliases", []):
            if alias in FORBIDDEN_ALIASES:
                hits.append(f"{f.relative_to(REPO)}: alias {alias!r}")
    assert not hits, f"core-only agents must stay unmanifested: {hits}"

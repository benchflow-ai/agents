"""Every manifest must declare a unique agent name — duplicates make
``load_agents_from_dir`` raise and leave one agent silently unreachable."""
import collections
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_SKIP = {".git", "node_modules", "dist", "build", ".venv", "__pycache__"}


def test_no_duplicate_agent_names():
    names: collections.Counter[str] = collections.Counter()
    locs: dict[str, list[str]] = collections.defaultdict(list)
    for f in REPO.rglob("manifest.toml"):
        if any(part in _SKIP for part in f.relative_to(REPO).parts):
            continue
        data = tomllib.loads(f.read_text())
        name = data.get("name")
        if name:
            names[name] += 1
            locs[name].append(str(f.relative_to(REPO)))
    dups = {n: locs[n] for n, c in names.items() if c > 1}
    assert not dups, f"duplicate agent names across manifests: {dups}"

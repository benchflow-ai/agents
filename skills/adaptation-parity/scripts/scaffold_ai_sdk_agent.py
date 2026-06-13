#!/usr/bin/env python3
"""Scaffold a new AI SDK BenchFlow adapter package from the ai-sdk/acp template.

  python scaffold_ai_sdk_agent.py <name>   # e.g. ai-sdk-foo  ->  ai-sdk/foo

Copies ai-sdk/acp -> ai-sdk/<name>, renames the Python package
(ai_sdk_acp -> ai_sdk_<name>) and the agent name, leaving a ready-to-edit
skeleton (server.mjs, register.py, pyproject.toml, tests, README). Edit
server.mjs's agent loop + register.py's env_mapping for your agent, then verify
with acp_capture.mjs + parity_diff.py (see SKILL.md).
"""
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # skills/adaptation-parity/scripts -> repo root
TEMPLATE = REPO / "ai-sdk" / "acp"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    name = re.sub(r"^ai-sdk-?", "", sys.argv[1]).strip("-/") or sys.argv[1]
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    dst = REPO / "ai-sdk" / name
    if dst.exists():
        sys.exit(f"refuse: {dst} already exists")
    if not TEMPLATE.exists():
        sys.exit(f"template missing: {TEMPLATE}")

    shutil.copytree(TEMPLATE, dst, ignore=shutil.ignore_patterns(
        ".pytest_cache", ".ruff_cache", "__pycache__", "*.pyc"))
    (dst / "src" / "ai_sdk_acp").rename(dst / "src" / f"ai_sdk_{slug}")

    subs = {"ai_sdk_acp": f"ai_sdk_{slug}", "ai-sdk-acp": f"ai-sdk-{name}",
            "ai-sdk/acp": f"ai-sdk/{name}", '"ai-sdk"': f'"ai-sdk-{name}"'}
    for f in dst.rglob("*"):
        if f.is_file() and f.suffix in {".py", ".toml", ".md", ".mjs"}:
            t = f.read_text()
            for a, b in subs.items():
                t = t.replace(a, b)
            f.write_text(t)

    print(f"scaffolded {dst}")
    print(f"  - edit src/ai_sdk_{slug}/server.mjs  (the agent loop)")
    print(f"  - edit src/ai_sdk_{slug}/register.py (name='ai-sdk-{name}', env_mapping)")
    print("  - add a per-package CI workflow in .github/workflows/")
    print("  - verify parity: acp_capture.mjs + parity_diff.py (SKILL.md)")


if __name__ == "__main__":
    main()

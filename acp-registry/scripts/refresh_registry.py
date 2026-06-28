#!/usr/bin/env python3
"""Refresh the ACP registry snapshot and report drift against the catalog.

    python scripts/refresh_registry.py            # diff only (no write)
    python scripts/refresh_registry.py --write     # update registry.snapshot.json

The ACP registry is published at a versioned CDN URL. This fetches the latest,
diffs it against our vendored snapshot + catalog, and prints what changed —
agents added/removed, version bumps — so a maintainer knows what to reclassify.
It never edits ``catalog.py`` (classification is a human judgement); it only
updates the snapshot when ``--write`` is passed.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

REGISTRY_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
SNAPSHOT = Path(__file__).parents[1] / "registry.snapshot.json"

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from acp_registry import BY_ID  # noqa: E402


def _fetch() -> dict:
    with urllib.request.urlopen(REGISTRY_URL, timeout=30) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def main() -> int:
    write = "--write" in sys.argv[1:]
    live = _fetch()
    snap = json.loads(SNAPSHOT.read_text())

    live_ids = {a["id"]: a.get("version") for a in live["agents"]}
    snap_ids = {a["id"]: a.get("version") for a in snap["agents"]}

    added = sorted(set(live_ids) - set(snap_ids))
    removed = sorted(set(snap_ids) - set(live_ids))
    bumped = sorted(
        rid
        for rid in set(live_ids) & set(snap_ids)
        if live_ids[rid] != snap_ids[rid]
    )
    uncatalogued = sorted(set(live_ids) - set(BY_ID))

    print(f"live: {len(live_ids)} agents (registry v{live.get('version')})")
    print(f"snapshot: {len(snap_ids)} agents (v{snap.get('version')})")
    if added:
        print(f"\n+ added in registry (classify these): {added}")
    if removed:
        print(f"\n- removed from registry: {removed}")
    if bumped:
        print("\n~ version bumps:")
        for rid in bumped:
            print(f"    {rid}: {snap_ids[rid]} -> {live_ids[rid]}")
    if uncatalogued:
        print(f"\n! in registry but NOT in catalog.py: {uncatalogued}")
    if not (added or removed or bumped):
        print("\nno agent-set drift.")

    if write:
        SNAPSHOT.write_text(json.dumps(live, indent=2) + "\n")
        print(f"\nwrote {SNAPSHOT}")
        print("Now reconcile catalog.py + regenerate AGENTS.md.")

    return 1 if uncatalogued else 0


if __name__ == "__main__":
    raise SystemExit(main())

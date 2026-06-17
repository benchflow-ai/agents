"""Regression for fix #3 (.daytona / SKIP_SEED seed-skip).

``seedIntoSession`` copies the task cwd into MiMo's per-session workdir so MiMo
operates on the real task. But ``.daytona`` is Daytona's root-owned per-sandbox
infra dir living in the task cwd; copying it makes MiMo's own writes under the
session dir fail with EACCES as the non-root sandbox user. So ``SKIP_SEED`` must
exclude ``.daytona`` (and symlinks), while still seeding the real task files.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

_PKG = Path(__file__).parents[1] / "src" / "ai_sdk_harness_mimo"
_SERVER = _PKG / "server.mjs"
_SERVER_SRC = _SERVER.read_text()
_MOCK_OK = Path(__file__).parent / "_mock_mimo_ok.mjs"


# ── cheap source invariant (no node needed) ──


def test_server_skips_daytona_in_seed() -> None:
    assert "SKIP_SEED" in _SERVER_SRC
    assert '".daytona"' in _SERVER_SRC
    # symlinks are skipped too (root-owned/loop hazards)
    assert "isSymbolicLink()" in _SERVER_SRC


# ── behavioural regression: drive the real server.mjs and inspect the session dir ──

_node = shutil.which("node") or next(
    (p for p in ("/opt/benchflow/node/bin/node",) if Path(p).exists()), None
)


def _find_node_modules() -> Path | None:
    seen = [
        Path("/opt/benchflow/js-agents/ai-sdk-mimo/node_modules"),
        Path("/tmp/pr9-repro/node_modules"),
    ]
    for anc in [_PKG, *_PKG.parents]:
        seen.append(anc / "node_modules")
    for nm in seen:
        if (nm / "@ai-sdk" / "harness").exists():
            return nm
    return None


_NM = _find_node_modules()


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


@pytest.mark.skipif(
    _node is None or _NM is None, reason="node or @ai-sdk/harness deps not installed"
)
def test_seed_copies_task_files_but_skips_daytona(tmp_path: Path) -> None:
    """A task cwd with a real file + a `.daytona` dir: after a turn the per-session
    mimo dir must contain the real file but NOT `.daytona`."""
    os.chmod(_MOCK_OK, 0o755)
    (tmp_path / "node_modules").symlink_to(_NM)
    server = tmp_path / "server.mjs"
    server.write_text(_SERVER_SRC)

    work = tmp_path / "work"
    work.mkdir()
    (work / "test.bib").write_text("@article{x, title={t}}\n")
    daytona = work / ".daytona"
    daytona.mkdir()
    (daytona / "infra").write_text("root-owned-ish\n")

    env = {
        **os.environ,
        "MIMO_BIN": str(_MOCK_OK),
        "BENCHFLOW_PROVIDER_MODEL": "mimo/mimo-auto",
        "OPENAI_BASE_URL": "",
        "OPENAI_API_KEY": "",
    }
    proc = subprocess.Popen(
        [_node, str(server)],
        cwd=str(tmp_path),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )

    def send(obj: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": False, "writeTextFile": False},
                        "terminal": False,
                    },
                },
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session/new",
                "params": {"cwd": str(work), "mcpServers": []},
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "session/set_model",
                "params": {"modelId": "mimo/mimo-auto"},
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "session/prompt",
                "params": {
                    "prompt": [{"type": "text", "text": "list the bib entries"}]
                },
            }
        )

        # seeding happens during ensureSession() on the first turn; poll for the
        # session dir to appear and be populated (no fixed sleep — robust to pacing).
        deadline = time.time() + 20
        seeded = None
        while time.time() < deadline:
            assert proc.poll() in (None, 0), "server crashed during seeding"
            dirs = list(work.glob("mimo-*"))
            if dirs and (dirs[0] / "test.bib").exists():
                seeded = dirs[0]
                break
            time.sleep(0.1)

        assert seeded is not None, "session dir was never seeded with the task file"
        assert (seeded / "test.bib").exists(), "real task file must be seeded"
        assert not (seeded / ".daytona").exists(), (
            ".daytona must be skipped (SKIP_SEED)"
        )
    finally:
        _kill_group(proc)

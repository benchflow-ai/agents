"""Regression: the inner `mimo acp` child dying mid-turn must NOT crash or hang
the outer ACP server — it must return a clean session/prompt result so the
benchflow run stays trackable (reward != None) instead of `pipe_closed` (rc=255).

Root cause (diagnosed 2026-06-16): in the 2GB Daytona sandbox the inner `mimo
acp` node child was OOM-killed ~58s into citation-check; makeAcpClient never
rejected the pending session/prompt (hang) and a later stdin write EPIPE-crashed
the process (rc=255). The fix: failPending on child death + non-throwing writes
+ a process-level safety net.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

_PKG = Path(__file__).parents[1] / "src" / "ai_sdk_harness_mimo"
_SERVER = _PKG / "server.mjs"
_SERVER_SRC = _SERVER.read_text()
_MOCK = Path(__file__).parent / "_mock_mimo_die.mjs"


# ── cheap source invariants (no node needed) — keep the hardening from rotting ──

def test_server_rejects_pending_on_inner_child_death() -> None:
    # failPending-on-death contract (mirrors omnigent _mimo_acp.py).
    assert "failPending" in _SERVER_SRC
    assert 'child.on("exit"' in _SERVER_SRC
    assert 'child.on("error"' in _SERVER_SRC
    assert 'child.stdout.on("close"' in _SERVER_SRC


def test_server_has_process_level_safety_net() -> None:
    assert 'process.on("uncaughtException"' in _SERVER_SRC
    assert 'process.on("unhandledRejection"' in _SERVER_SRC


def test_server_guards_writes_to_inner_child() -> None:
    # the bare `child.stdin.write(...)` in request/notify/reply is gone — every
    # write now goes through the non-throwing `write(` helper, and an EPIPE on the
    # child pipe is explicitly swallowed.
    assert _SERVER_SRC.count("child.stdin.write") <= 1
    assert 'child.stdin.on("error"' in _SERVER_SRC


# ── behavioural regression: drive the real server.mjs against a dying mock ──────

_node = shutil.which("node") or next(
    (p for p in ("/opt/benchflow/node/bin/node",) if Path(p).exists()), None
)


def _find_node_modules() -> Path | None:
    """Locate an installed node_modules that has @ai-sdk/harness (ESM resolves
    bare imports by walking up from the server module's dir)."""
    seen: list[Path] = [
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


@pytest.mark.skipif(_node is None or _NM is None, reason="node or @ai-sdk/harness deps not installed")
def test_inner_child_death_midturn_returns_clean_result(tmp_path: Path) -> None:
    os.chmod(_MOCK, 0o755)
    # a runnable copy of the server where its bare imports resolve
    (tmp_path / "node_modules").symlink_to(_NM)
    server = tmp_path / "server.mjs"
    server.write_text(_SERVER_SRC)
    work = tmp_path / "work"
    work.mkdir()

    env = {
        **os.environ,
        "MIMO_BIN": str(_MOCK),
        "BENCHFLOW_PROVIDER_MODEL": "mimo/mimo-auto",
        "OPENAI_BASE_URL": "",
        "OPENAI_API_KEY": "",
    }
    proc = subprocess.Popen(
        [_node, str(server)], cwd=str(tmp_path),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        start_new_session=True,
    )

    def send(obj: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def alive() -> None:
        rc = proc.poll()
        assert rc in (None, 0), f"server crashed rc={rc}; the inner-child death was not handled"

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": 1,
                         "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}})
        time.sleep(0.4)
        alive()
        send({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(work), "mcpServers": []}})
        time.sleep(0.4)
        alive()
        send({"jsonrpc": "2.0", "id": 3, "method": "session/set_model", "params": {"modelId": "mimo/mimo-auto"}})
        time.sleep(0.4)
        alive()
        # this turn's inner child dies mid-stream (mock exits 137 after a tool_call)
        send({"jsonrpc": "2.0", "id": 4, "method": "session/prompt",
              "params": {"prompt": [{"type": "text", "text": "find fake citations"}]}})

        # the outer server MUST answer id:4 within a few seconds (not hang) and
        # MUST NOT crash (rc != 0) while we wait.
        assert proc.stdout is not None
        deadline = time.time() + 15
        got_id4 = False
        out_lines: list[str] = []
        while time.time() < deadline and not got_id4:
            r, _, _ = select.select([proc.stdout], [], [], 0.2)
            if r:
                line = proc.stdout.readline()
                if not line:
                    break
                out_lines.append(line.strip())
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("id") == 4 and "result" in msg:
                    got_id4 = True
            alive()

        assert got_id4, f"server hung — no session/prompt result after inner child died. stdout={out_lines!r}"
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait(timeout=5)

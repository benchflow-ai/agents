"""Regression: the `mimo` CLI launcher is `#!/usr/bin/env node`, so it needs
`node` on PATH. The sandbox launches server.mjs by ABSOLUTE node path without
node on PATH (no system node), so the launcher exited 127 -> 0 tokens/0 tools ->
suspected_api_error (reward None). The fix prepends the running node's own dir to
PATH for every child server.mjs spawns.

Root cause diagnosed 2026-06-16 from a patched-but-still-None Daytona run whose
trajectory showed: "[harness error] mimo acp child gone: exited code=127".
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


def _kill_group(proc: subprocess.Popen) -> None:
    """Reap the whole process group — the healthy mock + any bash children stay
    alive after a bare proc.kill() and would hang the test runner's stdout pipe."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass

_PKG = Path(__file__).parents[1] / "src" / "ai_sdk_harness_mimo"
_SERVER = _PKG / "server.mjs"
_SERVER_SRC = _SERVER.read_text()
_MOCK_OK = Path(__file__).parent / "_mock_mimo_ok.mjs"

_node = shutil.which("node") or next(
    (p for p in ("/opt/benchflow/node/bin/node",) if Path(p).exists()), None
)


def _find_node_modules() -> Path | None:
    seen = [Path("/opt/benchflow/js-agents/ai-sdk-mimo/node_modules"), Path("/tmp/pr9-repro/node_modules")]
    for anc in [_PKG, *_PKG.parents]:
        seen.append(anc / "node_modules")
    for nm in seen:
        if (nm / "@ai-sdk" / "harness").exists():
            return nm
    return None


_NM = _find_node_modules()


def test_server_puts_node_dir_on_child_path() -> None:
    # source invariant: the fix is present and explained.
    assert "dirname(process.execPath)" in _SERVER_SRC
    assert "process.env.PATH" in _SERVER_SRC


@pytest.mark.skipif(_node is None or _NM is None, reason="node or deps not installed")
def test_shebang_node_launcher_runs_with_node_off_ambient_path(tmp_path: Path) -> None:
    """Run server.mjs with a PATH that has bash/sh/env but NOT node (mimics the
    sandbox), and a shebang-`node` mock launcher. Without the fix the launcher
    exits 127; with it, node is found and the turn completes with a tool call."""
    os.chmod(_MOCK_OK, 0o755)

    # a PATH dir with the basics but deliberately NO node
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("env", "bash", "sh"):
        real = shutil.which(tool)
        if real:
            (bindir / tool).symlink_to(real)
    assert shutil.which("node", path=str(bindir)) is None, "test bindir must not expose node"

    (tmp_path / "node_modules").symlink_to(_NM)
    server = tmp_path / "server.mjs"
    server.write_text(_SERVER_SRC)
    work = tmp_path / "work"
    work.mkdir()

    # minimal env — crucially PATH lacks node; the server (run by abs node path)
    # must add its own node dir so the launcher's shebang resolves.
    env = {
        "PATH": str(bindir),
        "HOME": str(tmp_path),
        "MIMO_BIN": str(_MOCK_OK),
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

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": 1,
                         "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}})
        time.sleep(0.4)
        send({"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": str(work), "mcpServers": []}})
        time.sleep(0.4)
        send({"jsonrpc": "2.0", "id": 3, "method": "session/set_model", "params": {"modelId": "mimo/mimo-auto"}})
        time.sleep(0.4)
        send({"jsonrpc": "2.0", "id": 4, "method": "session/prompt",
              "params": {"prompt": [{"type": "text", "text": "list the bib entries"}]}})

        assert proc.stdout is not None
        deadline = time.time() + 15
        id4: dict | None = None
        saw_tool_call = False
        out_lines: list[str] = []
        while time.time() < deadline and id4 is None:
            r, _, _ = select.select([proc.stdout], [], [], 0.2)
            if not r:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            out_lines.append(line.strip())
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            upd = (msg.get("params") or {}).get("update") or {}
            if upd.get("sessionUpdate") == "tool_call":
                saw_tool_call = True
            if msg.get("id") == 4 and "result" in msg:
                id4 = msg

        # IMPORTANT: server.mjs keeps its ACP event loop alive (it never exits on
        # its own), so a blocking `proc.stderr.read()` would wait for an EOF that
        # never arrives and hang the suite. Tear the process group down FIRST,
        # then drain whatever stderr was buffered (now EOF-bounded).
        _kill_group(proc)
        err = ""
        try:
            if proc.stderr is not None:
                err = proc.stderr.read() or ""
        except Exception:
            err = ""
        assert "code=127" not in err and "env: " not in err, f"launcher 127'd — node not on child PATH. stderr={err[-400:]!r}"
        assert id4 is not None, f"no turn result; stdout={out_lines!r} stderr={err[-400:]!r}"
        assert saw_tool_call, f"launcher ran but produced no tool call; stdout={out_lines!r}"
    finally:
        _kill_group(proc)

"""Regression for the proxy-credential leak (greptile P1 security finding).

In proxy mode ``createMimoSession`` writes a per-session ``.mimocode/mimocode.json``
custom provider so the turn routes through benchflow's usage proxy. The original
code wrote the raw ``OPENAI_API_KEY`` *value* into that file, and ``syncBackToCwd``
blindly copied the whole session dir back to ``agentCwd`` — so after every turn the
proxy API key sat on disk in the task artifact dir the verifier reads/archives.

Two independent defenses, each its own test:
  1. the provider config references the key via ``{env:OPENAI_API_KEY}`` (OpenCode
     config interpolation) — the secret value is never written to any file; and
  2. ``syncBackToCwd`` skips ``.mimocode`` so the harness-injected provider config
     never reaches ``agentCwd`` regardless.
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
_MOCK_RECORD = Path(__file__).parent / "_mock_mimo_record.mjs"


# ── cheap source invariants (no node needed) — keep the fix from rotting ──


def test_apikey_is_env_reference_not_literal() -> None:
    """The provider config must reference the key via OpenCode's {env:...}
    interpolation, never embed the raw process.env value on disk."""
    assert "{env:OPENAI_API_KEY}" in _SERVER_SRC, (
        "apiKey must be written as the {env:OPENAI_API_KEY} reference"
    )
    # the old literal-embedding form must be gone
    assert 'apiKey: process.env.OPENAI_API_KEY || "benchflow"' not in _SERVER_SRC, (
        "must not embed the raw OPENAI_API_KEY value into mimocode.json"
    )


def test_syncback_skips_credential_dir() -> None:
    """syncBackToCwd must exclude .mimocode (a boundary-private dir) so the proxy
    provider config never reaches agentCwd."""
    # the sync-back loop must consult the same boundary-skip predicate as seeding,
    # i.e. there is a single guard applied in both directions.
    assert _SERVER_SRC.count("isBoundaryPrivate") >= 2, (
        "a shared boundary-skip predicate must guard BOTH seed and sync-back"
    )
    assert '".mimocode"' in _SERVER_SRC, ".mimocode must be a boundary-private name"


# ── behavioural regression: drive the real server.mjs with OPENAI_BASE_URL set ──

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


def _wait_for_result(proc: subprocess.Popen, want_id: int, deadline: float) -> bool:
    """Read JSON-RPC lines from the server's stdout until the response for
    ``want_id`` arrives (i.e. runPrompt finished → sync-back ran). Returns True
    on success, False on timeout/crash. Draining stdout also keeps the pipe from
    blocking the server."""
    assert proc.stdout is not None
    while time.time() < deadline:
        if proc.poll() not in (None, 0):
            return False
        r, _, _ = select.select([proc.stdout], [], [], 0.2)
        if not r:
            continue
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            msg = json.loads(line.strip())
        except Exception:
            continue
        if msg.get("id") == want_id and "result" in msg:
            return True
    return False


_CANARY = "sk-proxy-CANARY-do-not-leak-7Z9"


@pytest.mark.skipif(
    _node is None or _NM is None, reason="node or @ai-sdk/harness deps not installed"
)
def test_proxy_key_never_lands_on_disk(tmp_path: Path) -> None:
    """After a full proxy-mode turn: (a) no mimocode.json anywhere contains the
    raw key value, (b) the config references it via {env:OPENAI_API_KEY}, and
    (c) the task cwd (agentCwd) has no .mimocode dir synced back into it."""
    os.chmod(_MOCK_RECORD, 0o755)
    (tmp_path / "node_modules").symlink_to(_NM)
    server = tmp_path / "server.mjs"
    server.write_text(_SERVER_SRC)
    work = tmp_path / "work"
    work.mkdir()
    (work / "test.bib").write_text("@article{x, title={t}}\n")
    record = tmp_path / "set_model.txt"

    env = {
        **os.environ,
        "MIMO_BIN": str(_MOCK_RECORD),
        "MIMO_RECORD_FILE": str(record),
        "BENCHFLOW_PROVIDER_MODEL": "deepseek/deepseek-v4-flash",
        "OPENAI_BASE_URL": "http://127.0.0.1:9/proxy",
        "OPENAI_API_KEY": _CANARY,
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
                "params": {"modelId": "deepseek/deepseek-v4-flash"},
            }
        )
        send(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "session/prompt",
                "params": {"prompt": [{"type": "text", "text": "find fake citations"}]},
            }
        )

        # block until the prompt turn completes — that is when syncBackToCwd has run.
        assert _wait_for_result(proc, 4, time.time() + 25), (
            "proxy turn never completed (so sync-back never ran)"
        )

        cfgs = list(tmp_path.rglob(".mimocode/mimocode.json"))
        assert cfgs, "no .mimocode/mimocode.json was written in proxy mode"

        # (a) + (b): the secret value is never on disk; the env reference is.
        for cfg_path in cfgs:
            text = cfg_path.read_text()
            assert _CANARY not in text, f"raw proxy key leaked into {cfg_path}"
            cfg = json.loads(text)
            apikey = cfg["provider"]["benchflow"]["options"]["apiKey"]
            assert apikey == "{env:OPENAI_API_KEY}", (
                f"apiKey must be the env reference, got {apikey!r}"
            )

        # (c): the credential dir must not have been synced back into agentCwd.
        assert not (work / ".mimocode").exists(), (
            ".mimocode (proxy provider config) leaked into agentCwd via sync-back"
        )
        # belt & suspenders: the canary must not appear in any file at the agentCwd
        # top level (i.e. outside the mimo-* session dir).
        for p in work.iterdir():
            if p.name.startswith("mimo-"):
                continue
            if p.is_file():
                assert _CANARY not in p.read_text(errors="ignore"), (
                    f"raw proxy key leaked into agentCwd file {p}"
                )
    finally:
        _kill_group(proc)

"""Regression for fix #4 (proxy raw-LLM custom provider).

When benchflow runs with usage tracking on it sets ``OPENAI_BASE_URL`` to its
LiteLLM usage proxy and passes a ``benchflow-*`` model alias. MiMo (an OpenCode
fork) would reject an unknown alias via ``models.dev`` UNLESS it belongs to a
custom provider. So ``createMimoSession`` must, when ``OPENAI_BASE_URL`` is set,
write a per-session ``.mimocode/mimocode.json`` registering an OpenAI-compatible
custom provider ``benchflow`` at the proxy and send the inner ACP
``session/set_model`` as ``benchflow/<alias>`` — so the turn routes THROUGH the
proxy (raw-LLM ``llm_trajectory.jsonl`` + ``usage_source=provider_response``)
rather than bypassing it. Losing this is the merge-readiness blocker, so it gets
both a cheap source invariant and a behavioural drive of the real server.mjs.
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
_MOCK_RECORD = Path(__file__).parent / "_mock_mimo_record.mjs"


# ── cheap source invariants (no node needed) — keep the proxy wiring from rotting ──


def test_server_writes_custom_provider_in_proxy_mode() -> None:
    # gated on OPENAI_BASE_URL, writes a mimocode.json custom provider, routes
    # the inner model as benchflow/<alias>.
    assert "OPENAI_BASE_URL" in _SERVER_SRC
    assert "mimocode.json" in _SERVER_SRC
    assert '"@ai-sdk/openai-compatible"' in _SERVER_SRC
    assert "benchflow: {" in _SERVER_SRC or "benchflow:" in _SERVER_SRC
    assert '"benchflow/" + alias' in _SERVER_SRC


def test_server_fails_loud_when_proxy_provider_write_fails() -> None:
    # silent fallback to the bare alias would lose the raw-LLM trajectory; the fix
    # must throw instead so the broken proxy wiring surfaces.
    assert "could not write" in _SERVER_SRC and "throw new Error" in _SERVER_SRC


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


@pytest.mark.skipif(
    _node is None or _NM is None, reason="node or @ai-sdk/harness deps not installed"
)
def test_proxy_mode_writes_mimocode_and_routes_benchflow_alias(tmp_path: Path) -> None:
    """With OPENAI_BASE_URL set + a benchflow-* alias, the real server.mjs must
    write a .mimocode/mimocode.json custom provider and send the inner model as
    benchflow/<alias>. Recorded by a mock that captures the set_model id."""
    os.chmod(_MOCK_RECORD, 0o755)
    (tmp_path / "node_modules").symlink_to(_NM)
    server = tmp_path / "server.mjs"
    server.write_text(_SERVER_SRC)
    work = tmp_path / "work"
    work.mkdir()
    record = tmp_path / "set_model.txt"

    proxy_base = "http://127.0.0.1:9/proxy"  # never dialled — turn ends before any POST
    # benchflow passes the model with a provider prefix; createMimoSession derives
    # the alias as the last path segment (here "deepseek-v4-flash").
    model_in = "deepseek/deepseek-v4-flash"
    env = {
        **os.environ,
        "MIMO_BIN": str(_MOCK_RECORD),
        "MIMO_RECORD_FILE": str(record),
        "BENCHFLOW_PROVIDER_MODEL": model_in,
        "OPENAI_BASE_URL": proxy_base,
        "OPENAI_API_KEY": "test-proxy-key",
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
                "params": {"modelId": model_in},
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

        # wait for the inner set_model to be recorded (the turn drives session
        # creation -> set_model). Poll on the file rather than a fixed sleep.
        deadline = time.time() + 20
        while time.time() < deadline and not (
            record.exists() and record.read_text().strip()
        ):
            assert proc.poll() in (None, 0), (
                "server crashed before recording inner set_model"
            )
            time.sleep(0.1)

        assert record.exists() and record.read_text().strip(), (
            "inner set_model was never recorded"
        )
        inner_model = record.read_text().strip()
        assert inner_model == "benchflow/deepseek-v4-flash", (
            f"inner model must be the custom-provider route, got {inner_model!r}"
        )

        # the per-session custom-provider config must exist with the proxy baseURL.
        cfgs = list(tmp_path.rglob(".mimocode/mimocode.json"))
        assert cfgs, "no .mimocode/mimocode.json was written in proxy mode"
        cfg = json.loads(cfgs[0].read_text())
        prov = cfg.get("provider", {}).get("benchflow", {})
        assert prov.get("npm") == "@ai-sdk/openai-compatible", (
            f"wrong provider npm: {prov!r}"
        )
        assert prov.get("options", {}).get("baseURL") == proxy_base, (
            "provider baseURL must be the proxy"
        )
        assert "deepseek-v4-flash" in prov.get("models", {}), (
            "alias must be registered as a model"
        )
    finally:
        _kill_group(proc)

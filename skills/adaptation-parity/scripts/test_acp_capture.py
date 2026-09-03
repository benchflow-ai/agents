"""Integration tests for ACP capture/smoke CLIs and shared driver."""

import json
import os
import shlex
import socket
import subprocess
import time
import tomllib
from pathlib import Path

import pytest
from parity import assert_wire_parity, compare_captures

HERE = Path(__file__).parent
CAPTURE = HERE / "acp_capture.mjs"
SMOKE = HERE / "acp_smoke.mjs"
FIXTURE = HERE / "acp_fixture.mjs"
PROVIDER_ENV = set(json.loads((HERE / "provider_env.json").read_text()))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def probe_args(
    tmp_path: Path,
    script: Path = CAPTURE,
    mode: str = "launch",
    port: int | None = None,
) -> list[str]:
    target = str(FIXTURE) if mode == "server" else shlex.join(["node", str(FIXTURE)])
    args = [
        "node",
        str(script),
        f"--{mode}",
        target,
        "--port",
        str(port or free_port()),
        "--cwd",
        str(tmp_path),
        "--rpc-timeout",
        "750",
    ]
    if script == CAPTURE:
        args += ["--out", str(tmp_path / "capture.jsonl")]
    return args


def run(args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        capture_output=True,
        timeout=10,
        env={**os.environ, **env},
    )


def test_empty_captures_fail() -> None:
    result = compare_captures([], [])
    assert not result.ok
    with pytest.raises(AssertionError, match="expected=0 actual=0"):
        assert_wire_parity([], [])


def test_provider_denylist_covers_manifest_mapping_targets() -> None:
    repo = HERE.parents[2]
    targets = {
        target
        for manifest in (repo / "acp").glob("*/manifest.toml")
        for target in tomllib.loads(manifest.read_text())
        .get("env_mapping", {})
        .values()
    }
    assert targets <= PROVIDER_ENV, (
        f"missing provider env: {sorted(targets - PROVIDER_ENV)}"
    )


@pytest.mark.parametrize("mode", ["server", "launch"])
def test_capture_modes_drive_strict_acp_and_mock(mode: str, tmp_path: Path) -> None:
    preserved = {
        "DB_HOST": "db.internal",
        "GITHUB_TOKEN": "github-fixture",
        "OPENCLAW_GATEWAY_TOKEN": "openclaw-fixture",
        "DATA_MODEL": "domain-fixture",
    }
    proc = run(
        probe_args(tmp_path, mode=mode),
        **dict.fromkeys(PROVIDER_ENV, "must-not-leak"),
        **preserved,
        EXPECT_PRESERVED_ENV=",".join(preserved),
        EXPECT_SCRUBBED_ENV=",".join(PROVIDER_ENV),
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["stopReason"] == "end_turn"
    assert (tmp_path / "callback.txt").read_text() == "callback-ok"
    record = json.loads((tmp_path / "capture.jsonl").read_text())
    assert record["tag"] == "capture"
    assert record["body"]["model"] == "mock-model"
    assert record["body"]["tools"][0]["function"]["name"] == "fixtureTool"


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("exit", "agent exited"),
        ("malformed", "malformed ACP JSON"),
        ("null", "malformed ACP message"),
        ("primitive", "malformed ACP message"),
        ("array", "malformed ACP message"),
        ("hang", "timed out"),
        ("rpc-error", "ACP session/prompt failed: fixture RPC rejection"),
    ],
)
def test_capture_errors_clean_process_tree(
    mode: str, error: str, tmp_path: Path
) -> None:
    child_pid = tmp_path / "child.pid"
    port = free_port()
    proc = run(
        probe_args(tmp_path, port=port),
        ACP_FIXTURE_MODE=mode,
        ACP_FIXTURE_CHILD_PID=str(child_pid),
    )
    assert proc.returncode == 1
    assert error in proc.stderr
    pid = int(child_pid.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail(f"agent descendant {pid} survived cleanup")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


@pytest.mark.parametrize("escape", ["../escape.txt", "absolute"])
def test_fs_callbacks_reject_cwd_escape(escape: str, tmp_path: Path) -> None:
    target = tmp_path.parent / "escape.txt"
    path = str(target) if escape == "absolute" else escape
    proc = run(probe_args(tmp_path), ACP_FIXTURE_PATH=path)
    assert proc.returncode == 1
    assert "fs callback rejected: ACP filesystem path escapes cwd" in proc.stderr
    assert not target.exists()


def test_fs_callbacks_reject_symlink_escape(tmp_path: Path) -> None:
    target = tmp_path.parent / "outside.txt"
    target.write_text("outside")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    proc = run(probe_args(tmp_path), ACP_FIXTURE_PATH=str(link))
    assert proc.returncode == 1
    assert target.read_text() == "outside"


def test_fs_callbacks_reject_dangling_symlink_escape(tmp_path: Path) -> None:
    target = tmp_path.parent / "missing-outside.txt"
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    proc = run(probe_args(tmp_path), ACP_FIXTURE_PATH=str(link))
    assert proc.returncode == 1
    assert "dangling symlink" in proc.stderr
    assert not target.exists()


def test_capture_does_not_set_model_by_default(tmp_path: Path) -> None:
    proc = run(probe_args(tmp_path), ACP_FIXTURE_MODE="reject-set-model")
    assert proc.returncode == 0, proc.stderr


def test_smoke_uses_shared_driver(tmp_path: Path) -> None:
    proc = run([*probe_args(tmp_path, SMOKE), "--set-model"])
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["sessionId"] == "strict-session"
    assert result["upstreamRequests"] == 1


def test_capture_isolates_and_cleans_agent_home(tmp_path: Path) -> None:
    """Capture must not read or mutate the caller's real agent configuration."""
    ambient_home = tmp_path / "ambient-home"
    ambient_home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    proc = run(
        probe_args(workspace),
        HOME=str(ambient_home),
        ACP_FIXTURE_HOME_MARKER="capture-marker",
    )

    assert proc.returncode == 0, proc.stderr
    assert not (ambient_home / "capture-marker").exists()


def test_capture_rejects_occupied_mock_port(tmp_path: Path) -> None:
    """Guards PR #71's occupied-port failure on IPv4 and dual-stack hosts."""
    port = free_port()
    with socket.socket() as occupied:
        occupied.bind(("0.0.0.0", port))
        occupied.listen()
        proc = run([*probe_args(tmp_path, port=port), "--ready-timeout", "250"])
    assert proc.returncode == 1
    assert "mock" in proc.stderr and "port" in proc.stderr


@pytest.mark.parametrize("cli", ["capture", "smoke"])
def test_clis_reject_no_upstream_request(cli: str, tmp_path: Path) -> None:
    args = probe_args(tmp_path, CAPTURE if cli == "capture" else SMOKE)
    proc = run(args, ACP_FIXTURE_MODE="no-upstream")
    assert proc.returncode == 1
    assert "without a fresh upstream request" in proc.stderr


def test_capture_truncates_stale_output(tmp_path: Path) -> None:
    output = tmp_path / "capture.jsonl"
    output.write_text('{"tag":"capture","body":{"model":"stale"}}\n')
    proc = run(probe_args(tmp_path, mode="server"), ACP_FIXTURE_MODE="no-upstream")
    assert proc.returncode == 1
    assert output.read_text() == ""


@pytest.mark.parametrize("mode_args", [[], ["--server", "x", "--launch", "x"]])
def test_capture_rejects_invalid_launch_modes(mode_args: list[str]) -> None:
    proc = run(["node", str(CAPTURE), *mode_args])
    assert proc.returncode == 2
    assert "usage:" in proc.stderr

"""Uniform offline wire-parity test for every agent in the ``ai-sdk/`` path (ADR-0002).

ONE mechanism, applied identically to all ``ai-sdk/<agent>/`` packages: re-drive the
SHIPPED ``src/*/server.mjs`` through one prompt against the deterministic capturing
mock upstream and assert the freshly-captured upstream requests are byte-identical
(modulo the reviewable ``NEUTRAL_DIFFS`` allowlist) to the committed standalone
*vanilla* fixture (``tests/fixtures/vanilla.jsonl``), plus outcome parity against
``tests/fixtures/summary.json``.

Each agent contributes ONLY data (a recorded fixture); the test logic lives here once.
Drop a ``tests/fixtures/vanilla.jsonl`` (+ ``summary.json``) into a package to activate it.
No live model is used: the mock IS the upstream, so the run is hermetic and reproducible.

Agents whose native runtime is a task-coupled or cloud sandbox cannot be captured in a
bare temp dir without modifying the upstream harness; they SKIP with a documented reason
(``SANDBOX_COUPLED``) until a representative-env capture is recorded.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent
_CAPTURE = _SCRIPTS / "acp_capture.mjs"

sys.path.insert(0, str(_SCRIPTS))

from parity import (  # noqa: E402
    assert_wire_parity,
    compare_captures,
    load_capture,
)

# Agents whose server.mjs runs inside a task-coupled / cloud sandbox: the hermetic
# bare-temp-dir acp_capture cannot drive them without modifying the upstream harness.
SANDBOX_COUPLED = {
    "harness-pi": (
        "just-bash sandbox bridges into a benchflow task cwd (seeds task files into a "
        "pi-<session> dir, then syncs back); a bare temp cwd has no task to bridge. "
        "Capture needs a representative task env, not the hermetic mock harness."
    ),
    "harness-codex": (
        "@ai-sdk/sandbox-vercel runs the agent loop in a Vercel cloud sandbox -- not "
        "offline-hermetic; capture needs Vercel infra."
    ),
    "harness-claude-code": (
        "@ai-sdk/sandbox-vercel runs the agent loop in a Vercel cloud sandbox -- not "
        "offline-hermetic; capture needs Vercel infra."
    ),
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; the offline re-drive requires Node")
    return node


def _require_node_deps(server: Path) -> None:
    """ESM resolves bare specifiers UP the dir chain from the server file; the shared
    ``ai-sdk/package.json`` install lands at ``ai-sdk/node_modules``. Skip cleanly when
    absent (e.g. ``npm ci`` not yet run) rather than false-failing."""
    p = server.parent
    while p != p.parent:
        if (p / "node_modules" / "ai").exists():
            return
        p = p.parent
    pytest.skip(
        "node deps absent (ai/...); run `npm ci` in ai-sdk/ to enable the re-drive"
    )


def _server_of(pkg_root: Path) -> Path:
    servers = sorted(pkg_root.glob("src/*/server.mjs"))
    assert len(servers) == 1, (
        f"{pkg_root.name}: expected exactly one src/*/server.mjs, found {servers}"
    )
    return servers[0]


def _redrive(server: Path, out: Path) -> dict:
    proc = subprocess.run(
        [
            _node(),
            str(_CAPTURE),
            "--server",
            str(server.resolve()),
            "--out",
            str(out),
            "--port",
            str(_free_port()),
            "--model",
            "deepseek-v4-flash",
        ],
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert proc.returncode == 0, (
        f"acp_capture.mjs exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return json.loads(proc.stdout[proc.stdout.index("{") :])


def make_parity_tests(pkg_root: Path):
    """Build the (re-drive, self-consistency) test pair for one ai-sdk package.

    The returned functions are identical in logic for every agent; the only per-agent
    inputs are the package dir, its server.mjs, and its committed fixture data.
    """
    pkg = pkg_root.name
    fixture = pkg_root / "tests" / "fixtures" / "vanilla.jsonl"
    summary_f = pkg_root / "tests" / "fixtures" / "summary.json"

    def test_offline_redrive_matches_vanilla_fixture(tmp_path: Path) -> None:
        if not fixture.exists():
            pytest.skip(
                SANDBOX_COUPLED.get(
                    pkg,
                    f"no recorded vanilla fixture for {pkg}; drop "
                    "tests/fixtures/vanilla.jsonl (+ summary.json) to activate",
                )
            )
        server = _server_of(pkg_root)
        _require_node_deps(server)
        out = tmp_path / "redrive.jsonl"
        got = _redrive(server, out)

        # Outcome parity vs the recorded baseline (data-driven; no hardcoded expectations).
        if summary_f.exists():
            want = json.loads(summary_f.read_text())
            assert got["stopReason"] == want["stopReason"]
            assert [t.split(" ", 1)[0] for t in got["toolCalls"]] == want[
                "toolCallNames"
            ]
            assert got["fileWritten"] == want["fileWritten"]

        # Wire parity: byte-identical-modulo-allowlist upstream requests.
        expected = load_capture(str(fixture))
        actual = load_capture(str(out))
        assert len(actual) == len(expected), (
            f"{pkg}: re-drive emitted {len(actual)} requests, fixture has {len(expected)}"
        )
        assert_wire_parity(expected, actual)

    def test_vanilla_fixture_is_loadable_and_self_consistent() -> None:
        if not fixture.exists():
            pytest.skip(
                SANDBOX_COUPLED.get(pkg, f"no recorded vanilla fixture for {pkg}")
            )
        cap = load_capture(str(fixture))
        assert cap, f"{pkg}: fixture is empty"
        assert compare_captures(cap, cap).ok

    return (
        test_offline_redrive_matches_vanilla_fixture,
        test_vanilla_fixture_is_loadable_and_self_consistent,
    )

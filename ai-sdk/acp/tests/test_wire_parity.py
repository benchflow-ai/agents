"""Offline wire-parity test for the ai-sdk/acp agent (ADR-0002).

Re-drives the SHIPPED ``server.mjs`` through one prompt against the deterministic
capturing mock upstream (``skills/adaptation-parity/scripts/{acp_capture,mock_upstream}.mjs``)
and asserts the freshly-captured upstream requests are byte-identical — modulo the
reviewable ``NEUTRAL_DIFFS`` allowlist — to the committed standalone *vanilla*
fixture (``tests/fixtures/vanilla.jsonl``).

This is the per-package offline guard that the agent's wire behavior has not
drifted from the recorded standalone baseline. It uses NO live model: the mock IS
the upstream, returning a fixed deterministic SSE response, so the run is hermetic
and reproducible.

The *symmetric* sandbox-cwd normalizer is what makes the assertion hold across
runs: the fixture was recorded in one temp cwd (``/tmp/parity-XXXX``) and every
re-drive runs in a *fresh* temp cwd. ``load_capture`` stamps each capture's OWN
recorded cwd and ``normalize_request`` collapses each to ``<CWD>`` — boundary
anchored on the cwd PREFIX only, so a genuinely different write *directory* would
still surface as a real divergence (see test_parity.py's over-collapse guards).
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[1]  # ai-sdk/acp
_REPO_ROOT = _PKG_ROOT.parents[1]  # repo root
_SCRIPTS = _REPO_ROOT / "skills" / "adaptation-parity" / "scripts"
_SERVER = _PKG_ROOT / "src" / "ai_sdk_acp" / "server.mjs"
_CAPTURE = _SCRIPTS / "acp_capture.mjs"
_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "vanilla.jsonl"

# Import the reusable parity comparator (pure-stdlib, no third-party deps) from the
# adaptation-parity scripts dir — the same module parity_diff.py and test_parity.py
# use, so the offline guard and the tooling unit tests share one normalizer.
sys.path.insert(0, str(_SCRIPTS))

from parity import (  # noqa: E402
    assert_wire_parity,
    compare_captures,
    load_capture,
)


def _free_port() -> int:
    """Grab an ephemeral port so parallel/repeat runs never collide on the mock."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; the offline re-drive requires Node")
    return node


def _require_node_deps() -> None:
    """``server.mjs`` imports ``ai`` / ``@ai-sdk/openai-compatible`` / ``zod`` as
    bare ESM specifiers, which Node resolves up the directory chain from the script
    (``NODE_PATH`` does NOT apply to ESM). So a ``node_modules`` must be installed
    at the package root (``npm ci`` in ai-sdk/acp). Skip cleanly when it is absent
    rather than false-failing — on a provisioned host the test RUNS."""
    if not (_PKG_ROOT / "node_modules" / "ai").exists():
        pytest.skip(
            "node deps not installed (ai / @ai-sdk/openai-compatible / zod); "
            "run `npm ci` in ai-sdk/acp to enable the offline re-drive"
        )


def _redrive(out_path: Path) -> dict:
    """Run the agent's ``server.mjs`` through one prompt against the capturing mock
    upstream and return acp_capture.mjs's JSON run summary. Each call uses a fresh
    temp cwd (created by acp_capture.mjs) recorded onto every captured line."""
    proc = subprocess.run(
        [
            _node(),
            str(_CAPTURE),
            "--server",
            str(_SERVER),
            "--out",
            str(out_path),
            "--port",
            str(_free_port()),
            "--model",
            "deepseek-v4-flash",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"acp_capture.mjs exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    # The run summary is the JSON object acp_capture.mjs prints to stdout.
    start = proc.stdout.index("{")
    return json.loads(proc.stdout[start:])


def test_offline_redrive_matches_vanilla_fixture(tmp_path: Path) -> None:
    """Re-drive the shipped server.mjs offline; assert byte-identical-modulo-
    allowlist wire parity with the committed standalone vanilla fixture."""
    _require_node_deps()
    out = tmp_path / "redrive.jsonl"
    summary = _redrive(out)

    # Outcome parity: the deterministic mock yields exactly one writeFile call,
    # end_turn, and the requested file content — a sanity gate before the wire diff.
    assert summary["stopReason"] == "end_turn"
    assert summary["fileWritten"] == "Hello, world!"
    assert [t.split(" ", 1)[0] for t in summary["toolCalls"]] == ["writeFile"]

    # Wire parity: the fresh capture (its own fresh temp cwd) vs the committed
    # vanilla fixture (its own temp cwd). The symmetric sandbox-cwd rule collapses
    # each side's OWN recorded cwd to <CWD>; everything the model conditions on
    # (messages, tools, sampling params) must then be byte-identical.
    expected = load_capture(str(_FIXTURE))
    actual = load_capture(str(out))
    assert len(expected) == 2, "fixture must hold the 2 upstream requests"
    assert len(actual) == 2, "re-drive must emit the 2 upstream requests"
    assert_wire_parity(expected, actual)


def test_vanilla_fixture_is_loadable_and_self_consistent() -> None:
    """The committed fixture is a valid 2-request capture that carries its own
    recorded cwd (so the symmetric-cwd collapse can anchor even without a re-drive)
    and is trivially wire-parity with itself."""
    cap = load_capture(str(_FIXTURE))
    assert len(cap) == 2
    assert compare_captures(cap, cap).ok

"""Prompt supervision and trajectory streaming coverage for OpenClaw."""

from __future__ import annotations

import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace


def test_parse_session_jsonl_emits_text_thought_tool_and_result(shim, tmp_path) -> None:
    """Guards BenchFlow PR #1075 JSONL-to-ACP trajectory mapping."""
    path = tmp_path / "session.jsonl"
    rows = [
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "plan"},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "shell",
                        "input": {"command": "pwd"},
                    },
                    {"type": "text", "text": "done"},
                ],
            },
        },
        {
            "type": "message",
            "message": {
                "role": "toolResult",
                "toolCallId": "t1",
                "content": [{"type": "text", "text": "out"}],
            },
        },
    ]
    path.write_text("not-json\n" + "\n".join(json.dumps(row) for row in rows))

    updates = shim.parse_session_jsonl(path, "session-1")

    assert [u["params"]["update"]["sessionUpdate"] for u in updates] == [
        "agent_thought",
        "tool_call",
        "text_update",
        "tool_call_update",
    ]
    assert all(u["params"]["sessionId"] == "session-1" for u in updates)


def test_parse_missing_session_is_safe_fallback(shim, tmp_path) -> None:
    """Guards BenchFlow PR #1075 missing-trajectory fallback."""
    assert shim.parse_session_jsonl(tmp_path / "missing.jsonl", "s") == []


def test_send_serializes_worker_and_dispatch_output(shim, monkeypatch) -> None:
    """Guards agents PR #73 against interleaved worker/dispatcher JSON-RPC."""

    class Sink:
        def __init__(self):
            self.guard = threading.Lock()
            self.active = 0
            self.max_active = 0
            self.lines = []

        def write(self, line):
            with self.guard:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.005)
            self.lines.append(line)
            with self.guard:
                self.active -= 1

        def flush(self):
            pass

    sink = Sink()
    monkeypatch.setattr(shim.sys, "stdout", sink)
    barrier = threading.Barrier(8)

    def emit(index):
        barrier.wait()
        shim.send({"index": index})

    threads = [threading.Thread(target=emit, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sink.max_active == 1
    assert sorted(json.loads(line)["index"] for line in sink.lines) == list(range(8))


def _row(text: str) -> str:
    return json.dumps(
        {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            },
        }
    )


def _prompt_thread(shim, monkeypatch, tmp_path, code: str, **kwargs):
    sessions = tmp_path / "sessions"
    sessions.mkdir(exist_ok=True)
    state = shim._PromptState()
    token = object()
    assert state.reserve(token)
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    worker = threading.Thread(
        target=shim._run_prompt,
        args=(
            state,
            token,
            3,
            "acp-session",
            (sys.executable, "-c", code, str(sessions)),
            dict(os.environ),
            sessions,
        ),
        kwargs={"poll_interval": 0.01, **kwargs},
    )
    state.set_worker(token, worker)
    worker.start()
    return state, worker, sent, sessions


def _wait_until(predicate, timeout: float = 3) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.01)


def test_prompt_streams_update_before_child_exit(shim, monkeypatch, tmp_path) -> None:
    """Guards agents PR #73 against hiding progress until child exit."""
    release = tmp_path / "release"
    code = f"""
import json, pathlib, sys, time
d = pathlib.Path(sys.argv[1]); p = d / 'live.jsonl'
p.write_text({(_row("live") + chr(10))!r})
while not pathlib.Path({str(release)!r}).exists(): time.sleep(.01)
print(json.dumps({{'meta': {{'agentMeta': {{'sessionId': 'live'}}}}}}))
"""
    state, worker, sent, _ = _prompt_thread(shim, monkeypatch, tmp_path, code)
    _wait_until(lambda: any(m.get("method") == "session/update" for m in sent))
    with state.lock:
        assert state.process.poll() is None
    release.touch()
    worker.join(3)
    assert not worker.is_alive()
    update_index = next(
        i for i, m in enumerate(sent) if m.get("method") == "session/update"
    )
    response_index = next(i for i, m in enumerate(sent) if m.get("id") == 3)
    assert update_index < response_index


def test_session_tailer_deduplicates_and_sticks(shim, tmp_path) -> None:
    """Guards agents PR #73 against stale, duplicate, or cross-session events."""
    old = tmp_path / "old.jsonl"
    old.write_text(_row("old") + "\n")
    tailer = shim._SessionTailer(tmp_path)
    old.write_text(old.read_text() + _row("new") + "\n")
    assert [u["params"]["update"]["text"] for u in tailer.poll("s")] == ["new"]
    assert tailer.poll("s") == []
    unrelated = tmp_path / "unrelated.jsonl"
    unrelated.write_text(_row("unrelated") + "\n")
    assert tailer.poll("s") == []
    old.write_text(old.read_text() + _row("later") + "\n")
    assert [u["params"]["update"]["text"] for u in tailer.drain("s", None)[0]] == [
        "later"
    ]


def test_session_tailer_reads_only_appends_and_buffers_partial_rows(
    shim, tmp_path
) -> None:
    """Guards agents PR #73 against quadratic polling and partial JSON loss."""
    path = tmp_path / "session.jsonl"
    path.write_text(_row("baseline") + "\n")
    tailer = shim._SessionTailer(tmp_path)
    row = _row("appended")
    split = len(row) // 2

    with path.open("a") as stream:
        stream.write(row[:split])
    assert tailer.poll("s") == []
    assert tailer.offset == path.stat().st_size
    assert tailer.pending

    with path.open("a") as stream:
        stream.write(row[split:] + "\n")
    updates = tailer.poll("s")
    assert [update["params"]["update"]["text"] for update in updates] == ["appended"]
    assert tailer.offset == path.stat().st_size
    assert tailer.pending == b""


def test_session_tailer_ambiguity_truncation_and_stdout_recovery(
    shim, tmp_path
) -> None:
    """Guards agents PR #73 ambiguity, replacement, and truncation handling."""
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text(_row("old-1") + "\n")
    second.write_text(_row("old-2") + "\n")
    ambiguous = shim._SessionTailer(tmp_path)
    first.write_text(first.read_text() + _row("new-1") + "\n")
    second.write_text(second.read_text() + _row("new-2") + "\n")
    assert ambiguous.poll("s") == []
    updates, diagnostic = ambiguous.drain("s", "second")
    assert [u["params"]["update"]["text"] for u in updates] == ["new-2"]
    assert diagnostic is None

    sticky = shim._SessionTailer(tmp_path)
    first.write_text(first.read_text() + _row("sticky") + "\n")
    assert sticky.poll("s")
    updates, diagnostic = sticky.drain("s", "second")
    assert updates == []
    assert "mismatch" in diagnostic
    first.write_text(_row("replacement") + "\n")
    assert [u["params"]["update"]["text"] for u in sticky.poll("s")] == ["replacement"]
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_text(_row("new-inode") + "\n")
    replacement.replace(first)
    assert [u["params"]["update"]["text"] for u in sticky.poll("s")] == ["new-inode"]


def test_session_tailer_detects_same_size_rewrite(shim, tmp_path) -> None:
    """Guards agents PR #73 against missing same-size session rewrites."""
    path = tmp_path / "session.jsonl"
    path.write_text(_row("first") + "\n")
    tailer = shim._SessionTailer(tmp_path)
    path.write_text(_row("added") + "\n")
    baseline_mtime_ns = tailer.baseline[path][3]
    os.utime(path, ns=(baseline_mtime_ns + 1, baseline_mtime_ns + 1))
    assert tailer.poll("s")
    mtime_ns = path.stat().st_mtime_ns
    path.write_text(_row("other") + "\n")
    os.utime(path, ns=(mtime_ns + 1, mtime_ns + 1))
    updates = tailer.poll("s")
    assert [u["params"]["update"]["text"] for u in updates] == ["other"]


def test_prompt_cancel_is_responsive_and_reaps(shim, monkeypatch, tmp_path) -> None:
    """Guards agents PR #73 cancellation latency and final event preservation."""
    code = f"""
import pathlib, sys, time
d = pathlib.Path(sys.argv[1]); (d / 'cancel.jsonl').write_text({(_row("cancel-final") + chr(10))!r})
time.sleep(30)
"""
    state, worker, sent, sessions = _prompt_thread(shim, monkeypatch, tmp_path, code)
    _wait_until(lambda: (sessions / "cancel.jsonl").exists())
    state.cancel()
    worker.join(3)
    assert not worker.is_alive()
    assert next(m for m in sent if m.get("id") == 3)["result"] == {
        "stopReason": "cancelled"
    }
    update = next(m for m in sent if m.get("method") == "session/update")
    terminal = next(m for m in sent if m.get("id") == 3)
    assert update["params"]["update"]["text"] == "cancel-final"
    assert sent.index(update) < sent.index(terminal)


def test_terminate_escalates_after_leader_exits_and_is_repeatable(
    shim, tmp_path
) -> None:
    """Guards agents PR #73 process-group cleanup and repeatable teardown."""
    child_pid_path = tmp_path / "child-pid"
    child_code = (
        "import os,pathlib,signal,sys,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time; subprocess.Popen(sys.argv[1:]); time.sleep(30)",
            sys.executable,
            "-c",
            child_code,
            str(child_pid_path),
        ],
        start_new_session=True,
    )
    try:
        _wait_until(child_pid_path.exists)
        child_pid = int(child_pid_path.read_text())
        shim._terminate_process_group(proc, grace=0.05)

        def child_stopped():
            try:
                return (
                    pathlib.Path(f"/proc/{child_pid}/stat").read_text().split()[2]
                    == "Z"
                )
            except FileNotFoundError:
                return True

        _wait_until(child_stopped)
        assert proc.returncode == -signal.SIGTERM
        shim._terminate_process_group(proc, grace=0.05)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def test_cancel_before_spawn_is_honored(shim, monkeypatch, tmp_path) -> None:
    """Guards agents PR #73 against losing cancellation during spawn."""
    state = shim._PromptState()
    token = object()
    assert state.reserve(token)
    state.cancel()
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    shim._run_prompt(
        state,
        token,
        3,
        "s",
        (sys.executable, "-c", "import time; time.sleep(30)"),
        dict(os.environ),
        tmp_path,
        poll_interval=0.01,
    )
    assert next(m for m in sent if m.get("id") == 3)["result"] == {
        "stopReason": "cancelled"
    }


def test_final_drain_and_large_capture_do_not_deadlock(
    shim, monkeypatch, tmp_path
) -> None:
    """Guards agents PR #73 final draining when child output exceeds pipe size."""
    code = f"""
import json, pathlib, sys
d = pathlib.Path(sys.argv[1]); (d / 'final.jsonl').write_text({(_row("final") + chr(10))!r})
sys.stderr.write('x' * 100000)
print('y' * 100000)
print(json.dumps({{'meta': {{'agentMeta': {{'sessionId': 'final'}}}}}}))
"""
    _, worker, sent, _ = _prompt_thread(shim, monkeypatch, tmp_path, code)
    worker.join(3)
    assert not worker.is_alive()
    assert any(
        m.get("params", {}).get("update", {}).get("text") == "final" for m in sent
    )
    diagnostic = next(
        m
        for m in sent
        if m.get("params", {}).get("update", {}).get("sessionUpdate") == "agent_thought"
    )
    assert len(diagnostic["params"]["update"]["text"]) <= shim._DIAG_TRUNCATE


def test_timeout_drains_update_and_preserves_end_turn(
    shim, monkeypatch, tmp_path
) -> None:
    """Guards agents PR #73 timeout draining and established stop semantics."""
    proc = SimpleNamespace(pid=123, stopped=False)
    proc.poll = lambda: 0 if proc.stopped else None
    proc.wait = lambda timeout=None: 0

    def popen(*args, **kwargs):
        sessions = pathlib.Path(args[0][-1])
        (sessions / "timeout.jsonl").write_text(_row("timeout-final") + "\n")
        return proc

    monkeypatch.setattr(shim.subprocess, "Popen", popen)
    monkeypatch.setattr(
        shim,
        "_terminate_process_group",
        lambda process: setattr(process, "stopped", True),
    )
    _, worker, sent, _ = _prompt_thread(shim, monkeypatch, tmp_path, "", timeout=0.5)
    worker.join(3)
    assert not worker.is_alive()
    update = next(m for m in sent if m.get("method") == "session/update")
    terminal = next(m for m in sent if m.get("id") == 3)
    assert update["params"]["update"]["text"] == "timeout-final"
    assert sent.index(update) < sent.index(terminal)
    assert terminal["result"] == {"stopReason": "end_turn"}
    assert any(
        "timed out after 0.5s"
        in message.get("params", {}).get("update", {}).get("text", "")
        for message in sent
    )


def test_normal_stdout_fallback_is_preserved(shim, monkeypatch, tmp_path) -> None:
    """Guards agents PR #73 legacy stdout fallback without a session file."""
    code = "import json; print(json.dumps({'payloads': [{'text': 'fallback'}]}))"
    _, worker, sent, _ = _prompt_thread(shim, monkeypatch, tmp_path, code)
    worker.join(3)
    assert not worker.is_alive()
    assert any(
        m.get("params", {}).get("update", {}).get("text") == "fallback" for m in sent
    )
    assert next(m for m in sent if m.get("id") == 3)["result"] == {
        "stopReason": "end_turn"
    }


def test_prompt_reaps_before_bounded_capture_reads(shim, monkeypatch, tmp_path) -> None:
    """Guards agents PR #73 bounded reads after process reaping."""
    proc = SimpleNamespace(pid=123, waited=False, poll=lambda: 0)

    def wait(timeout=None):
        proc.waited = True
        return 0

    proc.wait = wait
    read_limits = []

    class Capture(io.BytesIO):
        def seek(self, offset):
            assert offset == 0
            assert proc.waited
            return super().seek(offset)

        def read(self, limit):
            read_limits.append(limit)
            return super().read(limit)

    captures = iter([Capture(b'{"payloads":[{"text":"ok"}]}'), Capture(b"")])
    monkeypatch.setattr(shim.tempfile, "TemporaryFile", lambda: next(captures))
    monkeypatch.setattr(shim.subprocess, "Popen", lambda *args, **kwargs: proc)
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    state = shim._PromptState()
    token = object()
    assert state.reserve(token)
    shim._run_prompt(state, token, 3, "s", ("openclaw",), {}, tmp_path)
    assert read_limits == [shim._CAPTURE_LIMIT, shim._DIAG_TRUNCATE + 1]
    assert any(m.get("params", {}).get("update", {}).get("text") == "ok" for m in sent)


def test_prompt_spawn_error_is_protocol_error(shim, monkeypatch, tmp_path) -> None:
    """Guards agents PR #73 spawn failures at the ACP response boundary."""
    state = shim._PromptState()
    token = object()
    assert state.reserve(token)
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    shim._run_prompt(state, token, 3, "s", ("/missing/openclaw",), {}, tmp_path)
    assert next(m for m in sent if m.get("id") == 3)["error"]["code"] == -32603


def test_active_prompt_rejects_mutating_requests(shim, monkeypatch) -> None:
    """Guards agents PR #73 single-prompt state and cancel request semantics."""
    cancelled = threading.Event()

    def run_prompt(state, token, request_id, *args, **kwargs):
        assert cancelled.wait(2)
        state.finish(token)

    cancel_calls = 0
    original_cancel = shim._PromptState.cancel

    def cancel(state):
        nonlocal cancel_calls
        cancel_calls += 1
        original_cancel(state)
        cancelled.set()

    inbox = iter(
        [
            {"id": 1, "method": "session/prompt", "params": {"prompt": []}},
            {"id": 2, "method": "session/prompt", "params": {"prompt": []}},
            {"id": 3, "method": "session/new", "params": {"cwd": "/tmp"}},
            {"id": 4, "method": "session/set_model", "params": {"modelId": "x"}},
            {"method": "session/cancel", "params": {}},
            {"id": 5, "method": "session/cancel", "params": {}},
        ]
    )
    monkeypatch.setattr(shim, "setup_openai_auth", lambda: None)
    monkeypatch.setattr(shim, "setup_gcloud_adc", lambda: None)

    def recv():
        try:
            return next(inbox)
        except StopIteration as exc:
            raise EOFError from exc

    monkeypatch.setattr(shim, "recv", recv)
    monkeypatch.setattr(shim, "_run_prompt", run_prompt)
    monkeypatch.setattr(shim._PromptState, "cancel", cancel)
    sent = []
    monkeypatch.setattr(shim, "send", sent.append)
    shim.main()
    assert [
        next(m for m in sent if m.get("id") == i)["error"]["code"] for i in (2, 3, 4)
    ] == [
        -32600,
        -32600,
        -32600,
    ]
    assert next(m for m in sent if m.get("id") == 5)["result"] == {}
    assert not any(m.get("id", object()) is None for m in sent)
    assert cancel_calls == 3  # notification, request, EOF cleanup
    assert cancelled.is_set()

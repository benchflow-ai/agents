"""Supervise OpenClaw prompts and stream their session JSONL as ACP updates.

This module is intentionally stdlib-only: the manifest installs it beside the
executable shim in ``/opt/benchflow/bin``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, NamedTuple

logger = logging.getLogger(__name__)

DIAG_TRUNCATE = 2000
TOOL_RESULT_TRUNCATE = 1000
TOOL_INPUT_TRUNCATE = 500
PROMPT_TIMEOUT = 920.0
POLL_INTERVAL = 0.1
TERMINATE_GRACE = 2.0
CAPTURE_LIMIT = 1024 * 1024


def _message_update(session_id: str, update: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"sessionId": session_id, "update": update},
    }


def _entry_updates(entry: object, session_id: str) -> list[dict]:
    if not isinstance(entry, dict) or entry.get("type") != "message":
        return []

    message = entry.get("message")
    if not isinstance(message, dict):
        return []
    role = message.get("role", "")
    content = message.get("content", [])
    updates = []

    if role == "assistant" and isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                updates.append(
                    _message_update(
                        session_id,
                        {
                            "sessionUpdate": "text_update",
                            "text": block.get("text", ""),
                        },
                    )
                )
            elif block_type in ("tool_use", "toolCall"):
                tool_input = block.get("input", block.get("arguments", {}))
                if not isinstance(tool_input, dict):
                    tool_input = {"value": tool_input}
                title = tool_input.get(
                    "command",
                    tool_input.get("description", block.get("name", "tool")),
                )
                updates.append(
                    _message_update(
                        session_id,
                        {
                            "sessionUpdate": "tool_call",
                            "toolCallId": block.get("id", ""),
                            "kind": block.get("name", "tool"),
                            "title": title,
                            "status": "completed",
                            "content": [
                                {
                                    "type": "content",
                                    "content": {
                                        "type": "text",
                                        "text": json.dumps(tool_input)[
                                            :TOOL_INPUT_TRUNCATE
                                        ],
                                    },
                                }
                            ],
                        },
                    )
                )
            elif block_type == "thinking":
                updates.append(
                    _message_update(
                        session_id,
                        {
                            "sessionUpdate": "agent_thought",
                            "text": block.get("thinking", ""),
                        },
                    )
                )
    elif role == "toolResult":
        tool_id = message.get("toolCallId", "")
        if isinstance(content, list):
            result_text = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        elif isinstance(content, str):
            result_text = content
        else:
            result_text = ""
        updates.append(
            _message_update(
                session_id,
                {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": tool_id,
                    "status": "completed",
                    "content": [
                        {
                            "type": "content",
                            "content": {
                                "type": "text",
                                "text": result_text[:TOOL_RESULT_TRUNCATE],
                            },
                        }
                    ],
                },
            )
        )
    return updates


def _lines_updates(lines: list[bytes], session_id: str) -> list[dict]:
    updates = []
    for raw_line in lines:
        try:
            entry = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        updates.extend(_entry_updates(entry, session_id))
    return updates


def parse_session_jsonl(path: Path, session_id: str) -> list[dict]:
    """Convert all complete OpenClaw session JSONL rows to ACP updates."""
    try:
        return _lines_updates(path.read_bytes().splitlines(), session_id)
    except OSError:
        logger.debug("Failed to read session JSONL at %s", path, exc_info=True)
        return []


class _FileState(NamedTuple):
    device: int
    inode: int
    size: int
    mtime_ns: int


def _file_state(path: Path) -> _FileState | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return _FileState(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _unfinished_tail(path: Path, size: int) -> bytes:
    """Return a baseline file's unterminated final row without reading it all."""
    if size == 0:
        return b""
    chunk_size = 8192
    chunks = []
    remaining = size
    try:
        with path.open("rb") as stream:
            stream.seek(size - 1)
            if stream.read(1) == b"\n":
                return b""
            while remaining:
                length = min(chunk_size, remaining)
                remaining -= length
                stream.seek(remaining)
                chunk = stream.read(length)
                newline = chunk.rfind(b"\n")
                if newline >= 0:
                    chunks.append(chunk[newline + 1 :])
                    break
                chunks.append(chunk)
    except OSError:
        return b""
    return b"".join(reversed(chunks))


class SessionTailer:
    """Incrementally emit rows written during one OpenClaw prompt."""

    def __init__(self, sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.baseline = {
            path: state
            for path in self._paths()
            if (state := _file_state(path)) is not None
        }
        self.path: Path | None = None
        self.state: _FileState | None = None
        self.offset = 0
        self.pending = b""

    def _paths(self) -> list[Path]:
        if not self.sessions_dir.exists():
            return []
        return [
            path
            for path in self.sessions_dir.glob("*.jsonl")
            if not path.name.endswith(".lock")
        ]

    def _changed(self, path: Path, state: _FileState) -> bool:
        return self.baseline.get(path) != state

    def _select(self, path: Path, state: _FileState) -> None:
        old = self.baseline.get(path)
        continues_baseline = bool(
            old
            and (old.device, old.inode) == (state.device, state.inode)
            and (state.size > old.size or state.mtime_ns == old.mtime_ns)
        )
        self.path = path
        self.state = state
        self.offset = old.size if continues_baseline and old else 0
        self.pending = _unfinished_tail(path, self.offset) if self.offset else b""

    def _read(self, session_id: str, *, final: bool = False) -> list[dict]:
        if self.path is None:
            return []
        try:
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                data = stream.read()
                self.offset = stream.tell()
        except OSError:
            return []

        rows = (self.pending + data).splitlines(keepends=True)
        self.pending = b""
        if rows and not rows[-1].endswith((b"\n", b"\r")) and not final:
            self.pending = rows.pop()
        return _lines_updates(rows, session_id)

    def poll(self, session_id: str) -> list[dict]:
        selected = False
        if self.path is None:
            candidates = []
            for path in self._paths():
                state = _file_state(path)
                if state and self._changed(path, state):
                    candidates.append((path, state))
            if len(candidates) != 1:
                return []
            self._select(*candidates[0])
            selected = True

        state = _file_state(self.path)
        if state is None:
            return []
        if selected:
            return self._read(session_id)
        if state == self.state:
            return []
        assert self.state is not None
        replaced = (state.device, state.inode) != (
            self.state.device,
            self.state.inode,
        )
        rewritten = state.size < self.offset or (
            state.size == self.state.size and state.mtime_ns != self.state.mtime_ns
        )
        if replaced or rewritten:
            self.offset = 0
            self.pending = b""
        self.state = state
        return self._read(session_id)

    def drain(
        self, session_id: str, openclaw_session_id: str | None
    ) -> tuple[list[dict], str | None]:
        if (
            openclaw_session_id
            and Path(openclaw_session_id).name != openclaw_session_id
        ):
            return self._final_updates(session_id), (
                "[openclaw-acp-shim] invalid session ID in OpenClaw stdout"
            )
        expected = (
            self.sessions_dir / f"{openclaw_session_id}.jsonl"
            if openclaw_session_id
            else None
        )
        if expected and self.path and self.path != expected:
            streamed_name = self.path.name
            state = _file_state(expected)
            updates = self._updates_since_baseline(expected, state, session_id)
            return updates, (
                f"[openclaw-acp-shim] session JSONL mismatch: streamed "
                f"{streamed_name}, stdout identified {expected.name}"
            )
        if expected and self.path is None:
            state = _file_state(expected)
            if state:
                self._select(expected, state)
        return self._final_updates(session_id), None

    def _updates_since_baseline(
        self, path: Path, state: _FileState | None, session_id: str
    ) -> list[dict]:
        if state is None:
            return []
        old = self.baseline.get(path)
        continues_baseline = bool(
            old
            and (old.device, old.inode) == (state.device, state.inode)
            and (state.size > old.size or state.mtime_ns == old.mtime_ns)
        )
        offset = old.size if continues_baseline and old else 0
        pending = _unfinished_tail(path, offset) if offset else b""
        try:
            with path.open("rb") as stream:
                stream.seek(offset)
                return _lines_updates(
                    (pending + stream.read()).splitlines(), session_id
                )
        except OSError:
            return []

    def _final_updates(self, session_id: str) -> list[dict]:
        updates = self.poll(session_id)
        updates.extend(self._read(session_id, final=True))
        return updates


class PromptState:
    """Serialize prompt execution and carry cancellation across spawn races."""

    def __init__(self):
        self.lock = threading.Lock()
        self.token = None
        self.worker = None
        self.process = None
        self.cancelled = False

    def reserve(self, token) -> bool:
        with self.lock:
            if self.token is not None:
                return False
            self.token = token
            self.cancelled = False
            return True

    def set_worker(self, token, worker) -> None:
        with self.lock:
            if self.token == token:
                self.worker = worker

    def publish(self, token, process) -> bool:
        with self.lock:
            if self.token == token:
                self.process = process
            return self.token != token or self.cancelled

    def cancelled_for(self, token) -> bool:
        with self.lock:
            return self.token != token or self.cancelled

    def cancel(self) -> None:
        with self.lock:
            if self.token is not None:
                self.cancelled = True

    def active(self) -> bool:
        with self.lock:
            return self.token is not None

    def finish(self, token) -> None:
        with self.lock:
            if self.token == token:
                self.token = self.worker = self.process = None
                self.cancelled = False

    def worker_snapshot(self):
        with self.lock:
            return self.worker


def _signal_group(proc, signum: int) -> bool:
    try:
        os.killpg(proc.pid, signum)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def terminate_process_group(proc, grace: float = TERMINATE_GRACE) -> None:
    """Terminate the child's process group and always reap its leader."""
    group_alive = _signal_group(proc, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while group_alive and time.monotonic() < deadline:
        time.sleep(max(0, min(0.05, deadline - time.monotonic())))
        group_alive = _signal_group(proc, 0)
    if group_alive:
        _signal_group(proc, signal.SIGKILL)
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _openclaw_session_id(stdout: str) -> str | None:
    try:
        data = json.loads(stdout.strip())
        return data.get("meta", {}).get("agentMeta", {}).get("sessionId")
    except (json.JSONDecodeError, AttributeError, TypeError):
        match = re.search(r'"sessionId"\s*:\s*"([^"]+)"', stdout)
        return match.group(1) if match else None


def _thought(send: Callable[[dict], None], session_id: str, text: str) -> None:
    send(
        _message_update(
            session_id,
            {"sessionUpdate": "agent_thought", "text": text[:DIAG_TRUNCATE]},
        )
    )


def run_prompt(
    state: PromptState,
    token,
    request_id,
    session_id: str,
    command: tuple[str, ...],
    env: dict[str, str],
    sessions_dir: Path,
    *,
    send: Callable[[dict], None],
    terminate: Callable = terminate_process_group,
    timeout: float = PROMPT_TIMEOUT,
    poll_interval: float = POLL_INTERVAL,
) -> None:
    """Run one prompt while forwarding new events and honoring cancellation."""
    proc = None
    cancelled = False
    timed_out = False
    tailer = SessionTailer(sessions_dir)
    try:
        with (
            tempfile.TemporaryFile() as stdout_file,
            tempfile.TemporaryFile() as stderr_file,
        ):
            proc = subprocess.Popen(
                command,
                stdout=stdout_file,
                stderr=stderr_file,
                env=env,
                start_new_session=True,
            )
            cancelled = state.publish(token, proc)
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                for update in tailer.poll(session_id):
                    send(update)
                cancelled = cancelled or state.cancelled_for(token)
                timed_out = time.monotonic() >= deadline
                if cancelled or timed_out:
                    terminate(proc)
                    break
                time.sleep(poll_interval)
            else:
                proc.wait()

            stdout_file.flush()
            stderr_file.flush()
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read(CAPTURE_LIMIT).decode(errors="replace")
            stderr = stderr_file.read(DIAG_TRUNCATE + 1).decode(errors="replace")

            if stderr.strip():
                _thought(send, session_id, f"[openclaw stderr]\n{stderr}")

            updates, diagnostic = tailer.drain(session_id, _openclaw_session_id(stdout))
            for update in updates:
                send(update)
            if diagnostic:
                _thought(send, session_id, diagnostic)

            if tailer.path is None:
                try:
                    agent_text = (
                        json.loads(stdout).get("payloads", [{}])[0].get("text", "")
                    )
                except (json.JSONDecodeError, AttributeError, IndexError, KeyError):
                    agent_text = stdout[:DIAG_TRUNCATE]
                if agent_text:
                    send(
                        _message_update(
                            session_id,
                            {"sessionUpdate": "text_update", "text": agent_text},
                        )
                    )

            cancelled = cancelled or state.cancelled_for(token)
            if not cancelled and not timed_out and proc.returncode:
                raise RuntimeError(
                    f"OpenClaw exited with code {proc.returncode}: "
                    f"{(stderr.strip() or stdout.strip())[:DIAG_TRUNCATE]}"
                )
            if timed_out and not cancelled:
                message = f"OpenClaw prompt timed out after {timeout:g}s"
                _thought(send, session_id, f"[openclaw-acp-shim] {message}")
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"stopReason": "cancelled" if cancelled else "end_turn"},
                }
            )
    except Exception as exc:
        if proc is not None and proc.poll() is None:
            terminate(proc)
        send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(exc)},
            }
        )
    finally:
        state.finish(token)

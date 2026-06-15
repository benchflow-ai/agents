"""Pure ACP (Agent Client Protocol) bridge to MiMo Code's ``mimo acp`` server.

**No ``omnigent`` / ``fastapi`` imports** — this module is importable and
unit-testable standalone. It is *also* deployed verbatim into the installed
Omnigent's site-packages as ``omnigent/inner/_mimo_acp.py`` by the
``omnigent-mimo`` install overlay (see :mod:`omnigent.register`); keeping it
dependency-free is what lets the same source be both shipped-into-omnigent and
exercised by this package's tests without Omnigent present.

It speaks newline-delimited JSON-RPC over ``mimo acp``'s stdio (``mimo`` is an
OpenCode fork whose ``acp`` subcommand is a native ACP stdio server) and
translates ACP ``session/update`` notifications into **backend-neutral event
dicts** that :class:`omnigent.inner.mimo_executor.MimoExecutor` maps onto
Omnigent :class:`~omnigent.inner.executor.ExecutorEvent` variants.

Ported faithfully from the live-validated Workstream-A spike
(the ``@ai-sdk/harness`` ``HarnessAgent`` ↔ ``mimo acp`` adapter): identical ACP
handshake (``initialize`` → ``session/new`` → optional ``session/set_model`` →
``session/prompt``), identical ``session/update`` → event translation, identical
usage mapping, identical permission auto-allow. The only transport difference is
``asyncio`` subprocess streams instead of Node ``child_process``.

Neutral event dicts yielded by :meth:`MimoAcp.run_prompt` (``kind`` discriminator):

* ``{"kind": "text", "text": str}``            — assistant text delta
* ``{"kind": "reasoning", "text": str}``       — chain-of-thought delta
* ``{"kind": "tool_call", "id", "name", "args"}``   — a tool invocation
* ``{"kind": "tool_result", "id", "name", "result", "is_error"}`` — its outcome
* ``{"kind": "complete", "stop_reason", "usage"}``  — terminal: turn finished
* ``{"kind": "error", "message": str}``        — terminal: the prompt RPC failed

``complete``/``error`` is always the LAST item; exactly one is emitted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# MiMo's free, no-account, headless channel — the default gating/verification
# model (needs no API key, validated working in-sandbox). The flagship
# ``xiaomi/mimo-v2.5-pro`` is opportunistic and key/quota-gated.
DEFAULT_MODEL = "mimo/mimo-auto"

_ALLOW_RE = re.compile(r"allow|approve|yes", re.IGNORECASE)


def text_of(content: Any) -> str:
    """Flatten an ACP content block / list / string into plain text.

    ACP carries assistant + tool content as ``{"type": "text", "text": …}``
    blocks, nested ``{"type": "content", "content": …}`` wrappers, or bare
    strings/lists thereof. Mirrors the spike's ``textOf`` exactly so the wire
    translation is identical.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(text_of(c) for c in content)
    if isinstance(content, dict):
        ctype = content.get("type")
        if ctype == "text":
            return content.get("text") or ""
        if ctype == "content":
            return text_of(content.get("content"))
        if content.get("content") is not None:
            return text_of(content.get("content"))
        if content.get("text") is not None:
            return content.get("text") or ""
    return ""


def map_usage(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Map ACP ``usage`` onto Omnigent's ``TurnComplete.usage`` key shape.

    Known Omnigent keys: ``input_tokens`` / ``output_tokens`` /
    ``total_tokens`` (+ optional ``cache_read_input_tokens``). ``total_tokens``
    falls back to ``input + output`` when ACP does not report it.
    """
    usage = usage or {}
    inp = usage.get("inputTokens") or 0
    out = usage.get("outputTokens") or 0
    mapped: dict[str, Any] = {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": usage.get("totalTokens") or (inp + out),
    }
    if usage.get("cachedReadTokens") is not None:
        mapped["cache_read_input_tokens"] = usage["cachedReadTokens"]
    return mapped


def translate_update(update: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one ACP ``session/update`` ``update`` payload to a neutral event.

    Returns ``None`` for update kinds we intentionally ignore
    (``available_commands_update``, ``plan``, ``usage_update`` — usage is read
    off the ``session/prompt`` result instead, exactly like the spike).
    """
    kind = update.get("sessionUpdate")
    if kind == "agent_message_chunk":
        return {"kind": "text", "text": text_of(update.get("content"))}
    if kind == "agent_thought_chunk":
        return {"kind": "reasoning", "text": text_of(update.get("content"))}
    if kind == "tool_call":
        args = update.get("rawInput")
        if args is None:
            args = update.get("input")
        return {
            "kind": "tool_call",
            "id": update.get("toolCallId"),
            "name": update.get("title") or "tool",
            "args": args if isinstance(args, dict) else {},
        }
    if kind == "tool_call_update":
        status = update.get("status")
        if status in ("completed", "failed"):
            return {
                "kind": "tool_result",
                "id": update.get("toolCallId"),
                "name": update.get("title") or "tool",
                "result": text_of(update.get("content")) or status,
                "is_error": status == "failed",
            }
    return None


class MimoAcp:
    """Owns one ``mimo acp`` subprocess + ACP session (pure asyncio, no omnigent).

    Construct via :meth:`start` (does the spawn + handshake). One instance maps
    to one MiMo conversation; :meth:`run_prompt` drives one user turn and streams
    neutral events. :meth:`close` tears the subprocess down.
    """

    def __init__(self, proc: asyncio.subprocess.Process, model: str | None) -> None:
        self._proc = proc
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._update_handler: Any = None
        self.model = model
        self.acp_sid: str | None = None
        # True once a turn's ``instructions`` (system prompt) have been folded
        # into the first prompt — the executor checks this to avoid re-sending
        # the system prompt on every nudge turn.
        self.instructions_applied = False
        self._reader_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    # ── lifecycle ────────────────────────────────────────────────────────

    @classmethod
    async def start(
        cls,
        *,
        mimo_bin: str,
        cwd: str,
        model: str | None,
        env: dict[str, str],
    ) -> "MimoAcp":
        """Spawn ``mimo acp --cwd <cwd>`` and complete the ACP handshake.

        ``cwd`` is the task workspace (``/app`` in BenchFlow) — MiMo runs its
        own native edit/write/bash tools directly against it, so files land
        where the verifier reads. ``model`` is sent via ``session/set_model``
        (best-effort; falls back to MiMo's session default on rejection).
        """
        proc = await asyncio.create_subprocess_exec(
            mimo_bin,
            "acp",
            "--cwd",
            cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        self = cls(proc, model)
        await self._request(
            "initialize",
            {
                "protocolVersion": 1,
                # fs:false — MiMo uses its OWN filesystem tools against --cwd
                # (it has real FS access in the sandbox), so it never round-trips
                # reads/writes back through the client. terminal:false for the
                # same reason (native shell tool).
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                    "terminal": False,
                },
            },
        )
        new_session = await self._request("session/new", {"cwd": cwd, "mcpServers": []})
        self.acp_sid = (new_session or {}).get("sessionId")
        if model:
            try:
                await self._request(
                    "session/set_model",
                    {"sessionId": self.acp_sid, "modelId": model},
                )
            except Exception as exc:  # noqa: BLE001 — non-fatal: fall back to session default
                logger.warning("mimo acp session/set_model(%r) failed: %s", model, exc)
        logger.info(
            "mimo acp session %s ready (cwd=%s, model=%s)", self.acp_sid, cwd, model
        )
        return self

    async def close(self) -> None:
        """Best-effort: terminate the subprocess and cancel the reader tasks."""
        for task in (self._reader_task, self._stderr_task):
            task.cancel()
        try:
            self._proc.kill()
        except ProcessLookupError:
            pass
        except Exception as exc:  # noqa: BLE001 — close must never raise
            logger.warning("mimo acp close: kill failed: %s", exc)
        # Reap the process so its transport is torn down inside the running loop
        # (otherwise a late GC tries to write_eof after the loop closed).
        try:
            await self._proc.wait()
        except Exception:  # noqa: BLE001 — close must never raise
            pass

    # ── one user turn ────────────────────────────────────────────────────

    async def run_prompt(self, text: str) -> AsyncIterator[dict[str, Any]]:
        """Drive one ``session/prompt`` turn; stream neutral events then a terminal.

        ACP delivers all ``session/update`` notifications BEFORE the
        ``session/prompt`` response (the response is the turn's last wire line),
        so a single queue preserves ordering: notifications are translated +
        enqueued by the reader as they arrive, and the terminal sentinel is
        enqueued only after the response resolves.
        """
        queue: asyncio.Queue[Any] = asyncio.Queue()
        done = object()

        def handler(update: dict[str, Any]) -> None:
            event = translate_update(update)
            if event is not None:
                queue.put_nowait(event)

        self._update_handler = handler
        outcome: dict[str, Any] = {}

        async def drive() -> None:
            try:
                result = await self._request(
                    "session/prompt",
                    {
                        "sessionId": self.acp_sid,
                        "prompt": [{"type": "text", "text": text}],
                    },
                )
                outcome["result"] = result or {}
            except Exception as exc:  # noqa: BLE001 — surfaced as a terminal error event
                outcome["error"] = exc
            finally:
                queue.put_nowait(done)

        task = asyncio.create_task(drive())
        try:
            while True:
                item = await queue.get()
                if item is done:
                    break
                yield item
        finally:
            self._update_handler = None
            await task

        if "error" in outcome:
            yield {"kind": "error", "message": str(outcome["error"])}
            return
        result = outcome.get("result", {})
        yield {
            "kind": "complete",
            "stop_reason": result.get("stopReason"),
            "usage": map_usage(result.get("usage")),
        }

    # ── JSON-RPC plumbing ────────────────────────────────────────────────

    async def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        try:
            while True:
                raw = await self._proc.stdout.readline()
                if not raw:
                    break  # EOF — the mimo subprocess exited
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mid = msg.get("id")
                if mid is not None and mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        if msg.get("error") is not None:
                            fut.set_exception(RuntimeError(json.dumps(msg["error"])))
                        else:
                            fut.set_result(msg.get("result"))
                elif msg.get("method") and mid is not None:
                    self._on_server_request(msg)
                elif (
                    msg.get("method") == "session/update"
                    and self._update_handler is not None
                ):
                    update = (msg.get("params") or {}).get("update")
                    if update:
                        self._update_handler(update)
        finally:
            # The subprocess died (EOF) or the reader was cancelled: fail every
            # in-flight request so an awaiting ``run_prompt`` surfaces a terminal
            # error instead of hanging forever on a reply that will never come.
            self._fail_pending(RuntimeError("mimo acp process exited"))

    def _fail_pending(self, exc: Exception) -> None:
        pending, self._pending = self._pending, {}
        for fut in pending.values():
            if not fut.done():
                fut.set_exception(exc)

    async def _drain_stderr(self) -> None:
        assert self._proc.stderr is not None
        while True:
            raw = await self._proc.stderr.readline()
            if not raw:
                break
            logger.debug("mimo acp stderr: %s", raw.decode(errors="replace").rstrip())

    def _send(self, obj: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write((json.dumps(obj) + "\n").encode())

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        mid = self._next_id
        self._next_id += 1
        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        assert self._proc.stdin is not None
        await self._proc.stdin.drain()
        return await fut

    def _reply(self, mid: Any, result: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "id": mid, "result": result})

    def _on_server_request(self, msg: dict[str, Any]) -> None:
        """Auto-respond to server→client requests (permission prompts, probes).

        The dedicated sandbox is the isolation boundary, so any permission
        request is auto-allowed (matches the harness's danger-full-access
        posture); anything else gets a benign empty reply.
        """
        method = msg.get("method") or ""
        if "permission" in method:
            options = ((msg.get("params") or {}).get("options")) or []
            chosen = next(
                (
                    o
                    for o in options
                    if _ALLOW_RE.search(str(o.get("optionId") or o.get("name") or ""))
                ),
                options[0] if options else None,
            )
            option_id = (chosen or {}).get("optionId", "allow")
            self._reply(
                msg["id"], {"outcome": {"outcome": "selected", "optionId": option_id}}
            )
        else:
            self._reply(msg["id"], {})

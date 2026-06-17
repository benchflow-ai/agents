"""``MimoExecutor`` — MiMo Code's native ``mimo acp`` loop as an Omnigent harness.

**Deployed** into the host Omnigent's site-packages as
``omnigent/inner/mimo_executor.py`` by the ``omnigent-mimo`` install overlay (see
:func:`omnigent.register.register_mimo`). It is NOT imported by the
``omnigent-benchflow`` package itself (it imports real Omnigent internals +
``omnigent.inner._mimo_acp``), so it is verified by content assertions + the live
in-sandbox run rather than by import in this package's tests.

Faithful, not model-only: MiMo's OWN agent loop (plan → call its native
edit/write/bash tools → write files in the task cwd) runs each turn; this
:class:`Executor` only spawns ``mimo acp``, drives one ``session/prompt`` per
turn, and surfaces MiMo's events as Omnigent
:class:`~omnigent.inner.executor.ExecutorEvent` variants. This is the exact
relationship :class:`~omnigent.inner.pi_executor.PiExecutor` has to
``pi --mode rpc``. ``handles_tools_internally()`` is ``True`` because MiMo
executes its own tools — the Omnigent Session must not re-execute the observed
``ToolCallRequest``/``ToolCallComplete`` events.

MiMo is an OpenCode fork: it validates model ids against the models.dev catalog
and won't accept BenchFlow's bare ``benchflow-*`` proxy alias as a stock model
id. In **proxy mode** (``usage_tracking != off``) the bridge works around that by
registering a custom OpenAI-compatible provider at the proxy and routing the turn
as ``benchflow/<safe_model_alias>`` (see :meth:`MimoAcp.start`), so MiMo POSTs
every agent turn through BenchFlow's usage proxy and the kernel captures the raw
prompts + tokens (``usage_source=provider_response``). On the free
``mimo/mimo-auto`` channel (``usage_tracking=off``) there is no proxy: MiMo talks
straight to its own endpoint with the native model id, and the trace sidecar (see
below) is what surfaces tool use + native usage.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator

from omnigent.inner._mimo_acp import DEFAULT_MODEL, MimoAcp
from omnigent.inner.executor import (
    Executor,
    ExecutorConfig,
    ExecutorError,
    ReasoningChunk,
    TextChunk,
    ToolCallComplete,
    ToolCallRequest,
    ToolCallStatus,
    TurnComplete,
)

logger = logging.getLogger(__name__)


def _attach_tool_result(tools: list[dict[str, Any]], event: dict[str, Any]) -> None:
    """Fold a ``tool_result`` event into its matching pending ``tool_call`` trace.

    Correlates by tool-call id; falls back to the most recent result-less entry
    (MiMo always pairs them, but a missing id must not drop the result).
    """
    for record in reversed(tools):
        if record["id"] == event["id"] and record["result"] is None:
            record["result"] = event["result"]
            record["is_error"] = event["is_error"]
            return
    for record in reversed(tools):
        if record["result"] is None:
            record["result"] = event["result"]
            record["is_error"] = event["is_error"]
            return
    tools.append(
        {
            "id": event["id"],
            "name": event["name"],
            "args": {},
            "result": event["result"],
            "is_error": event["is_error"],
        }
    )


def _latest_user_text(messages: list[dict[str, Any]] | None) -> str:
    """Latest user message flattened to text (mirrors PiExecutor's extractor)."""
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            content = msg.get("content")
            if content is None:
                return ""
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and isinstance(p.get("text"), str)
                ]
                return " ".join(parts)
            return str(content)
    return ""


class MimoExecutor(Executor):
    """Drive ``mimo acp`` for one MiMo conversation behind the Executor contract.

    One ``mimo acp`` subprocess is started lazily on the first turn and reused
    across nudge turns; :meth:`close_session` / :meth:`close` tear it down. The
    model is fixed at spawn time (it is an ACP session property), so a per-turn
    ``config.model`` override that differs from the running session respawns it.
    """

    def __init__(
        self,
        *,
        cwd: str,
        model: str | None,
        mimo_path: str | None = None,
        env: dict[str, str] | None = None,
        trace_path: str | None = None,
    ) -> None:
        self._cwd = cwd
        self._model = model or DEFAULT_MODEL
        self._mimo_path = mimo_path or "mimo"
        self._env = {**os.environ, **(env or {})}
        self._acp: MimoAcp | None = None
        # When set, each turn's tool calls + native ACP usage are written here as
        # one JSON object so the out-of-sandbox ``OmnigentSession`` can surface
        # them to BenchFlow's trajectory. On the free ``mimo/mimo-auto`` channel
        # (usage_tracking=off) MiMo talks straight to its own endpoint, so the
        # proxy sees nothing — without this sidecar the run would show zero tokens
        # AND zero tool calls and trip BenchFlow's zero-activity guard (reward
        # nulled). In proxy mode the proxy ALSO captures the raw exchanges, but
        # the trace keeps the trajectory tool-step-auditable either way.
        self._trace_path = trace_path

    # ── Executor capability flags ────────────────────────────────────────

    def supports_streaming(self) -> bool:
        return True

    def supports_tool_calling(self) -> bool:
        return True

    def handles_tools_internally(self) -> bool:
        # MiMo runs its own tools; the Session must NOT re-execute them. The
        # observed ToolCallRequest/ToolCallComplete events are informational.
        return True

    # ── lifecycle ────────────────────────────────────────────────────────

    async def _ensure_acp(self, model: str) -> MimoAcp:
        if self._acp is not None and self._model == model:
            return self._acp
        if self._acp is not None:
            await self._acp.close()
            self._acp = None
        self._model = model
        self._acp = await MimoAcp.start(
            mimo_bin=self._mimo_path,
            cwd=self._cwd,
            model=model,
            env=self._env,
        )
        return self._acp

    async def close_session(self, session_key: str) -> None:  # noqa: ARG002 - single session per process
        await self.close()

    async def close(self) -> None:
        if self._acp is not None:
            await self._acp.close()
            self._acp = None

    # ── one turn ─────────────────────────────────────────────────────────

    async def run_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any],  # noqa: ARG002 - MiMo uses its own tools (handles_tools_internally)
        system_prompt: str,
        config: ExecutorConfig | None = None,
    ) -> AsyncIterator[Any]:
        """Drive one MiMo turn; yield streamed events then exactly one terminal.

        Yields :class:`TextChunk` / :class:`ReasoningChunk` /
        :class:`ToolCallRequest` / :class:`ToolCallComplete` as MiMo streams
        them, then a single :class:`TurnComplete` (``response=None`` — the final
        text already streamed as ``TextChunk``s; only ``usage`` is consumed by
        the adapter) or an :class:`ExecutorError` on a protocol/RPC failure.
        """
        model = (config.model if config else None) or self._model
        acp = await self._ensure_acp(model)

        text = _latest_user_text(messages)
        if not acp.instructions_applied and system_prompt:
            text = f"{system_prompt}\n\n{text}" if text else system_prompt
        acp.instructions_applied = True

        # Accumulate the turn's tool calls + native usage for the trace sidecar.
        trace_tools: list[dict[str, Any]] = []
        trace_usage: dict[str, Any] | None = None
        trace_text: list[str] = []
        try:
            async for event in acp.run_prompt(text):
                kind = event["kind"]
                if kind == "text":
                    if event["text"]:
                        trace_text.append(event["text"])
                        yield TextChunk(text=event["text"])
                elif kind == "reasoning":
                    if event["text"]:
                        yield ReasoningChunk(
                            delta=event["text"], event_type="reasoning_text"
                        )
                elif kind == "tool_call":
                    trace_tools.append(
                        {
                            "id": event["id"],
                            "name": event["name"],
                            "args": event["args"],
                            "result": None,
                            "is_error": False,
                        }
                    )
                    yield ToolCallRequest(
                        name=event["name"],
                        args=event["args"],
                        metadata={"call_id": event["id"]},
                    )
                elif kind == "tool_result":
                    _attach_tool_result(trace_tools, event)
                    yield ToolCallComplete(
                        name=event["name"],
                        status=ToolCallStatus.ERROR
                        if event["is_error"]
                        else ToolCallStatus.SUCCESS,
                        result=event["result"],
                        metadata={"call_id": event["id"]},
                    )
                elif kind == "error":
                    self._write_trace(trace_tools, trace_usage, trace_text)
                    yield ExecutorError(message=event["message"], retryable=False)
                    return
                elif kind == "complete":
                    trace_usage = event["usage"]
                    yield TurnComplete(response=None, usage=event["usage"])
        finally:
            self._write_trace(trace_tools, trace_usage, trace_text)

    def _write_trace(
        self,
        tools: list[dict[str, Any]],
        usage: dict[str, Any] | None,
        text: list[str],
    ) -> None:
        """Persist this turn's tool calls + usage as one JSON object.

        Read back by ``OmnigentSession`` (out of the sandbox) to emit ``tool_call``
        trajectory events + report native usage via ``latest_usage_totals``. The
        write must never break the turn — the model output already landed — but a
        failure is logged at ERROR (not warning): a missing trace makes a real run
        read as zero-activity, which BenchFlow would misdiagnose as an API error,
        so the operator needs to see the true (filesystem) cause. Writes to a temp
        file then atomically renames, so the reader never sees a half-written JSON.
        """
        if not self._trace_path:
            return
        payload = {"tools": tools, "usage": usage, "text": "".join(text)}
        tmp_path = f"{self._trace_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self._trace_path)
        except Exception:
            logger.exception(
                "mimo trace write to %s failed — tool/usage tracking degraded "
                "for this turn",
                self._trace_path,
            )

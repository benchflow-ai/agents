"""``OmnigentSession`` — a non-ACP :class:`~benchflow.agents.protocol.Session`.

The Agent plane is transport-agnostic (see ``benchflow.agents.protocol``): the
kernel drives a rollout through the ``Session`` Protocol, and ACP is only the
*first* concrete implementation. This module is a *second*: it drives one
Databricks **Omnigent** ``pi``-harness run behind the same contract — by
shelling ``omnigent run`` **inside the BenchFlow sandbox** via
:meth:`Sandbox.exec`, not by importing the ``omnigent-client`` SDK in-process.

Why in-sandbox subprocess and not the in-process SDK
----------------------------------------------------
Omnigent's runner pins ``starlette<1`` and brings its own (conflicting) FastAPI
/ litellm stack. Importing ``omnigent-client`` into the BenchFlow host process
(which already runs a litellm/starlette-1.x usage proxy) is unsupported and was
observed to break at import time. The supported, isolated path is to install
omnigent under its own ``uv tool`` environment **in the sandbox** (see
``register.py``) and invoke its one-shot CLI:

    omnigent run --harness pi --model <MODEL> -p "<text>"

``-p`` is genuinely one-shot — it runs a single turn against the ``pi`` harness
and exits (no REPL). The agent's file writes land in the sandbox workspace
``/app`` (the task cwd), exactly where BenchFlow's file-based verifier reads.
Model routing + credentials are written into the sandbox at ``connect()`` time
(``~/.omnigent/config.yaml``, built from ``agent_env``); see
:meth:`OmnigentAgent.connect`.

Trajectory wiring
-----------------
``OmnigentSession`` does **not** reuse :func:`make_trajectory_sink` — that
helper is bound to :class:`~benchflow.acp.session.ACPSession`'s private
event log. Instead this session owns a flat list of trajectory event dicts
in the *same on-disk shape* (``user_message`` / ``agent_message`` /
``agent_thought`` / ``tool_call``) and exposes:

* ``on_change`` — an assignable callback the kernel sets
  (``Rollout._attach_trajectory_writer``); it is invoked with ``self`` on
  every event so a writer can stream the trajectory to disk.
* ``steps`` — the accumulated event dicts (the Session-plane contract).

The subprocess path emits a ``user_message`` for the prompt and an
``agent_message`` for the harness's final output (plus an ``[error] …``
``agent_message`` on a nonzero exit). The canonical event shapes are kept in
lockstep with :mod:`benchflow.trajectories._capture`.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from benchflow.acp.types import StopReason
from benchflow.agents.protocol import AskUserHandler

if TYPE_CHECKING:  # pragma: no cover - typing only
    from benchflow.sandbox.protocol import Sandbox

logger = logging.getLogger(__name__)

# The task workspace cwd inside the sandbox (the BenchFlow task root). Omnigent
# runs here so the files it writes land where the file-based verifier reads.
_WORKSPACE = "/app"

# Sandbox-exec backstop timeout for ``omnigent run`` (seconds). This is NOT the
# authoritative per-turn timeout — the kernel wraps ``prompt()`` in
# ``asyncio.wait_for(timeout=<task agent budget>)`` (rollout
# ``_execute_session_prompts``), so the task's own ``[agent] timeout_sec`` is
# what bounds a turn. This value only stops a hung ``sandbox.exec`` from running
# unbounded if that kernel guard somehow doesn't fire; it must therefore sit
# ABOVE typical task budgets (600–900s+) or it would clip legitimate long turns
# (a hardcoded 600 once truncated tasks with a 900s budget). Override with
# ``BENCHFLOW_OMNIGENT_RUN_TIMEOUT_SEC`` for unusually long benchmarks.
_RUN_TIMEOUT_SEC = int(os.environ.get("BENCHFLOW_OMNIGENT_RUN_TIMEOUT_SEC", "1800"))

# Substrings that mark a stdout line as server/health/framework noise rather
# than substantive agent output. ``omnigent run`` spins its per-harness FastAPI
# wrap transiently, so uvicorn/starlette banners and INFO logs can interleave
# with the agent's text; we filter them when picking the final agent line.
_NOISE_MARKERS = (
    "uvicorn",
    "INFO:",
    "INFO ",
    "WARNING:",
    "WARNING ",
    "DEBUG:",
    "DEBUG ",
    "ERROR:",  # framework error logs; genuine agent errors are surfaced via stderr
    "Started server process",
    "Waiting for application startup",
    "Application startup complete",
    "Uvicorn running",
    "Shutting down",
    "Finished server process",
    "Application shutdown complete",
    "Started reloader process",
    "GET /",
    "POST /",
    "HTTP/1.1",
    "health",
    "/healthz",
)


def _is_noise(line: str) -> bool:
    """True when ``line`` is server/health/framework noise, not agent output."""
    stripped = line.strip()
    if not stripped:
        return True
    return any(marker in stripped for marker in _NOISE_MARKERS)


def _final_agent_line(stdout: str) -> str:
    """Extract the substantive agent output from ``omnigent run`` stdout.

    Drops server/health/uvicorn/INFO framework noise (see ``_NOISE_MARKERS``)
    and returns the remaining lines joined back into one text — the harness's
    answer with the transient FastAPI/uvicorn banners removed. Falls back to the
    full stdout (stripped) if every line was filtered, so we never silently drop
    the only output.
    """
    substantive = [ln for ln in stdout.splitlines() if not _is_noise(ln)]
    if not substantive:
        return stdout.strip()
    return "\n".join(substantive).strip()


class OmnigentSession:
    """A single Omnigent ``pi``-harness turn behind the ``Session`` contract.

    Drives ``omnigent run --harness pi -p <text>`` **inside the sandbox** via
    :meth:`Sandbox.exec`. Construct via :meth:`OmnigentAgent.connect` — never
    directly — so the sandbox handle, model, and credential config are wired in
    one place.
    """

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        model: str | None,
        exec_user: str = "root",
        harness: str = "pi",
    ) -> None:
        self._sandbox = sandbox
        self._model = model
        self._exec_user = exec_user
        # ``"pi"`` (omnigent-pi) or ``"mimo"`` (omnigent-mimo). Selects the
        # ``omnigent run --harness <harness>`` value; the mimo path also routes
        # the model + cwd via HARNESS_MIMO_* env and sources the gateway-cred
        # file written by ``OmnigentAgent.connect``.
        self._harness = harness
        self._ask_user_handler: AskUserHandler | None = None
        # Flat trajectory in the canonical on-disk event shape — see
        # benchflow.trajectories._capture._events_to_trajectory.
        self._events: list[dict] = []
        # Assignable by the kernel (Rollout._attach_trajectory_writer). Called
        # with ``self`` after every appended event so a writer streams to disk.
        self.on_change: Callable[[OmnigentSession], None] | None = None
        # MiMo trackability bridge: the in-sandbox MimoExecutor writes each turn's
        # tool calls + native ACP usage to this file (MiMo runs usage_tracking=off,
        # so the proxy sees nothing); ``prompt`` reads it back to emit ``tool_call``
        # events and accumulate cumulative usage, which the rollout collects via
        # ``latest_usage_totals``. Without this, a mimo run shows zero tokens AND
        # zero tool calls and BenchFlow nulls the reward as a suspected API error.
        # A uuid (not ``id(self)``) guarantees a unique path — the low bits of a
        # CPython object id collapse to a few values across sequential allocations.
        self._mimo_trace_path = f"/tmp/omnigent-mimo-trace-{uuid.uuid4().hex}.json"
        self._usage_totals: dict[str, int] = {}
        # Tool calls observed this rollout. Mirrors ``ACPSession.tool_calls`` (the
        # public mutable list the session-factory rollout reads via
        # ``len(session.tool_calls)`` to count ``n_tool_calls``) — populated from
        # the MiMo trace so the count reflects MiMo's native tool use. omnigent-pi
        # has no such list, which is why its trajectories report ``n_tool_calls=0``.
        self.tool_calls: list[dict] = []

    # ── Session Protocol ──────────────────────────────────────────────

    async def prompt(self, text: str) -> StopReason:
        """Run one ``omnigent run`` turn in the sandbox; return why it stopped.

        Emits a ``user_message`` for the prompt, shells the one-shot
        ``omnigent run`` CLI with cwd ``/app`` (stopping any stale daemon
        first, defensively), then emits one ``agent_message`` carrying the final
        substantive stdout line. A nonzero exit additionally emits an
        ``[error] …`` ``agent_message`` with the stderr tail. Each emit fires
        ``on_change`` so the trajectory streams to disk.
        """
        self._emit({"type": "user_message", "text": text})

        model = self._model or ""
        # ``omnigent stop`` is harmless if no daemon is running; it clears any
        # stale per-harness server left by a prior turn. ``omnigent run`` is the
        # one-shot turn (``-p`` exits after a single turn, no REPL). cwd=/app so
        # output files land where the verifier reads.
        #
        # MiMo harness path: source the gateway-cred env file (written by
        # connect; absent/empty on the free mimo/mimo-auto channel) so the API
        # key never appears in argv, and set the non-secret HARNESS_MIMO_CWD /
        # HARNESS_MIMO_MODEL inline. These reach mimo_harness.create_app() because
        # the harness subprocess inherits the `omnigent run` process env.
        mimo_prefix = ""
        if self._harness == "mimo":
            trace = shlex.quote(self._mimo_trace_path)
            mimo_env_exports = (
                'set -a; . "$HOME/.omnigent/mimo.env" 2>/dev/null || true; set +a; '
                f"rm -f {trace}; "  # clear any stale trace before this turn
                f"export HARNESS_MIMO_TRACE={trace}; "
                f"export HARNESS_MIMO_CWD={shlex.quote(_WORKSPACE)}; "
            )
            if model:
                mimo_env_exports += f"export HARNESS_MIMO_MODEL={shlex.quote(model)}; "
            mimo_prefix = mimo_env_exports
        cmd = (
            f"cd {shlex.quote(_WORKSPACE)} && "
            f"{mimo_prefix}"
            f"omnigent stop >/dev/null 2>&1; "
            f"omnigent run --harness {shlex.quote(self._harness)} --model {shlex.quote(model)} "
            f"-p {shlex.quote(text)}"
        )

        try:
            result = await self._sandbox.exec(
                cmd,
                user=self._exec_user,
                timeout_sec=_RUN_TIMEOUT_SEC,
            )
        except Exception as e:  # pragma: no cover - exec transport failure
            logger.error(f"OmnigentSession: omnigent run exec failed: {e}")
            self._emit(
                {"type": "agent_message", "text": f"[error] omnigent run failed: {e}"}
            )
            return StopReason.END_TURN

        # MiMo trackability: on a SUCCESSFUL run, read the in-sandbox trace and
        # emit ``tool_call`` events (so n_tool_calls > 0) + accumulate native usage
        # BEFORE the final agent_message, giving a sensibly ordered, step-auditable
        # trajectory. Skip on a non-zero exit — the trace may be partial, missing,
        # or (if the run never reached the executor) stale from a prior turn, and
        # ingesting it would attribute the previous turn's tools/usage to this one.
        if self._harness == "mimo" and result.return_code == 0:
            await self._ingest_mimo_trace()

        final = _final_agent_line(result.stdout)
        if final:
            self._emit({"type": "agent_message", "text": final})

        if result.return_code != 0:
            # Surface a bounded stderr tail in the trajectory; still END_TURN —
            # a failed turn ends the turn (the verifier judges the workspace).
            stderr_tail = (result.stderr or "").strip()[-2000:]
            self._emit(
                {
                    "type": "agent_message",
                    "text": (
                        f"[error] omnigent run exited {result.return_code}"
                        + (f": {stderr_tail}" if stderr_tail else "")
                    ),
                }
            )

        return StopReason.END_TURN

    async def _ingest_mimo_trace(self) -> None:
        """Read the MiMo turn's tool/usage sidecar and fold it into the trajectory.

        The in-sandbox :class:`MimoExecutor` wrote ``HARNESS_MIMO_TRACE`` as one
        JSON object ``{"tools": [...], "usage": {...}}``. We emit one canonical
        ``tool_call`` event per tool (``type``/``tool_call_id``/``kind``/``title``/
        ``status``/``content`` — the shape BenchFlow's metrics count), mirror them
        into ``self.tool_calls`` (the count the rollout reads), and add the turn's
        native ACP usage to the cumulative ``latest_usage_totals`` snapshot.

        Only called after a zero-exit run, so a missing/empty trace here means the
        in-sandbox executor could not write it (e.g. a full ``/tmp``) — that is
        surfaced as a visible ``agent_message`` rather than silently degrading to
        zero-activity (which BenchFlow would otherwise misdiagnose as an API
        error). A read/parse failure never raises — the turn's files already landed.
        """
        try:
            read = await self._sandbox.exec(
                f"cat {shlex.quote(self._mimo_trace_path)} 2>/dev/null || true",
                user=self._exec_user,
                timeout_sec=30,
            )
        except Exception as e:  # pragma: no cover - best-effort
            logger.warning(f"OmnigentSession: reading mimo trace failed: {e}")
            return

        raw = (read.stdout or "").strip()
        if not raw:
            # The run succeeded but the executor wrote no trace — make the gap
            # visible (and non-empty trajectory) instead of letting it read as a
            # silent zero-activity (suspected) API error.
            logger.error(
                "OmnigentSession: mimo run succeeded but wrote no trace at %s — "
                "tool/usage tracking degraded for this turn",
                self._mimo_trace_path,
            )
            self._emit(
                {
                    "type": "agent_message",
                    "text": "[warning] mimo trace unavailable — tool/usage "
                    "tracking degraded for this turn",
                }
            )
            return
        try:
            trace = json.loads(raw)
        except (ValueError, TypeError) as e:
            logger.warning(f"OmnigentSession: mimo trace not valid JSON: {e}")
            return

        for tool in trace.get("tools") or []:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "tool")
            event = {
                "type": "tool_call",
                "tool_call_id": str(tool.get("id") or ""),
                "kind": name,
                "title": name,
                "status": "error" if tool.get("is_error") else "completed",
                "content": tool.get("result"),
            }
            self.tool_calls.append(event)  # the count the rollout reads
            self._emit(event)

        usage = trace.get("usage")
        if isinstance(usage, dict):
            self._accumulate_usage(usage)

    def _accumulate_usage(self, usage: dict) -> None:
        """Add a turn's MiMo usage onto the cumulative ``latest_usage_totals`` snapshot."""
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cache_read_input_tokens",
        ):
            value = usage.get(key)
            if isinstance(value, int):
                self._usage_totals[key] = self._usage_totals.get(key, 0) + value

    def latest_usage_totals(self) -> dict[str, int] | None:
        """Cumulative native token usage for the rollout's usage collector.

        BenchFlow's session rollout reads this (``_collect_native_acp_usage`` →
        ``getattr(session, "latest_usage_totals")``) to attribute tokens when the
        agent runs usage_tracking=off — which MiMo must, since it rejects the
        LiteLLM proxy alias. Returns ``None`` until a turn reports usage so the
        collector skips cleanly (omnigent-pi has no such method and is unaffected).
        """
        return dict(self._usage_totals) if self._usage_totals else None

    async def cancel(self) -> None:
        """Best-effort abort: stop any in-flight omnigent daemon in the sandbox."""
        try:
            await self._sandbox.exec(
                f"cd {shlex.quote(_WORKSPACE)} && omnigent stop",
                user=self._exec_user,
                timeout_sec=30,
            )
        except Exception as e:  # pragma: no cover - best-effort cancel
            logger.warning(f"OmnigentSession cancel failed: {e}")

    def on_ask_user(self, handler: AskUserHandler) -> None:
        """Register the agent-initiated question handler (a no-op here).

        The omnigent ``run`` path is headless and one-shot, so it never elicits;
        the handler is stored only for ``Session`` contract symmetry with
        :class:`ACPSessionAdapter` and is intentionally never invoked.
        """
        self._ask_user_handler = handler  # stored for symmetry; never read

    @property
    def steps(self) -> list[Any]:
        """This session's ordered trajectory events — its rollout contribution."""
        return list(self._events)

    # ── Lifecycle (called by OmnigentAgent / Rollout) ─────────────────

    async def close(self) -> None:
        """Tear down the omnigent daemon + mimo session artifacts (best-effort)."""
        await self.cancel()
        if self._harness == "mimo":
            # Remove the trace sidecar and the gateway-cred env file so neither
            # the (tool-name/result) trace nor the raw API key lingers in the
            # sandbox after the session ends.
            try:
                await self._sandbox.exec(
                    f'rm -f {shlex.quote(self._mimo_trace_path)} "$HOME/.omnigent/mimo.env"',
                    user=self._exec_user,
                    timeout_sec=30,
                )
            except Exception as e:  # pragma: no cover - best-effort cleanup
                logger.warning(f"OmnigentSession: mimo artifact cleanup failed: {e}")

    # ── Internal: trajectory emission ─────────────────────────────────

    def _emit(self, event: dict) -> None:
        """Append a trajectory event and fire ``on_change``."""
        self._events.append(event)
        cb = self.on_change
        if cb is None:
            return
        try:
            cb(self)
        except Exception as e:  # pragma: no cover - sink must never break run
            logger.error(f"OmnigentSession on_change callback failed: {e}")

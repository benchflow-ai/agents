"""``OmnigentSession`` — a non-ACP :class:`~benchflow.agents.protocol.Session`.

The Agent plane is transport-agnostic (see ``benchflow.agents.protocol``): the
kernel drives a rollout through the ``Session`` Protocol, and ACP is only the
*first* concrete implementation. This module is a *second*: it drives one
Databricks **Omnigent** run behind the same contract, against the **selected**
harness (the ``--harness`` value wired in at construction; default ``pi``) — by
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

    omnigent run --harness <HARNESS> --model <MODEL> -p "<text>"

``-p`` is genuinely one-shot — it runs a single turn against the selected
harness and exits (no REPL). The agent's file writes land in the sandbox
workspace
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

import logging
import os
import shlex
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
    """A single Omnigent harness turn behind the ``Session`` contract.

    Drives ``omnigent run --harness <harness> -p <text>`` **inside the sandbox**
    via :meth:`Sandbox.exec`. Construct via :meth:`OmnigentAgent.connect` — never
    directly — so the sandbox handle, model, harness, and credential config are
    wired in one place.
    """

    def __init__(
        self,
        sandbox: Sandbox,
        *,
        model: str | None,
        exec_user: str = "root",
        harness: str = "pi",
        cwd: str | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._model = model
        self._exec_user = exec_user
        # Canonical ``omnigent --harness`` value baked into each per-turn run.
        self._harness = harness
        # Where ``omnigent run`` executes. The kernel resolves the per-rollout
        # workspace and plumbs it through (BENCHFLOW_AGENT_CWD → OmnigentAgent →
        # here); falls back to ``_WORKSPACE`` when unset so direct construction /
        # older core keep the historical ``/app`` default.
        self._cwd = cwd or _WORKSPACE
        self._ask_user_handler: AskUserHandler | None = None
        # Flat trajectory in the canonical on-disk event shape — see
        # benchflow.trajectories._capture._events_to_trajectory.
        self._events: list[dict] = []
        # Assignable by the kernel (Rollout._attach_trajectory_writer). Called
        # with ``self`` after every appended event so a writer streams to disk.
        self.on_change: Callable[[OmnigentSession], None] | None = None

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
        # one-shot turn (``-p`` exits after a single turn, no REPL). cwd is the
        # kernel-resolved workspace so output files land where the verifier reads.
        # ``--model`` (the benchmark model) is forwarded when set; omnigent's
        # runner routes every harness through the config.yaml gateway provider
        # written at connect() time, so no per-harness env is needed here.
        model_flag = f"--model {shlex.quote(model)} " if model else ""
        cmd = (
            f"cd {shlex.quote(self._cwd)} && "
            f"omnigent stop >/dev/null 2>&1; "
            f"omnigent run --harness {shlex.quote(self._harness)} "
            f"{model_flag}"
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

    async def cancel(self) -> None:
        """Best-effort abort: stop any in-flight omnigent daemon in the sandbox."""
        try:
            await self._sandbox.exec(
                f"cd {shlex.quote(self._cwd)} && omnigent stop",
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
        """Tear down any lingering omnigent daemon in the sandbox (best-effort)."""
        await self.cancel()

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

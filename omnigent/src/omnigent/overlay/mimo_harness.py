"""``harness: mimo`` wrap — the ``create_app()`` entrypoint.

**Deployed** into the host Omnigent's site-packages as
``omnigent/inner/mimo_harness.py`` by the ``omnigent-mimo`` install overlay (see
:func:`omnigent.register.register_mimo`), and registered in
``omnigent.runtime.harnesses._HARNESS_MODULES`` under the key ``"mimo"``. The
shared ``omnigent.runtime.harnesses._runner`` imports this module and calls
``create_app()`` to get the FastAPI app it serves — identical contract to
:mod:`omnigent.inner.pi_harness`.

All the REST/SSE wiring lives in
:class:`omnigent.runtime.harnesses._executor_adapter.ExecutorAdapter`; this wrap
only constructs a :class:`omnigent.inner.mimo_executor.MimoExecutor` from env.
The executor is built lazily on the first turn so an absent ``mimo`` CLI surfaces
as a request-time error, not an app-boot crash.

Env vars read at executor construction (set by ``OmnigentSession`` on the
``omnigent run --harness mimo`` invocation; the harness subprocess inherits
``os.environ`` via ``process_manager._build_harness_spawn_env``):

- ``HARNESS_MIMO_MODEL``: native MiMo model id, e.g. ``mimo/mimo-auto`` (free,
  default) or ``xiaomi/mimo-v2.5-pro``. ``None`` → MiMo session default.
- ``HARNESS_MIMO_CWD``: task workspace cwd (BenchFlow ``/app``). ``None`` →
  the runner's inherited cwd.
- ``HARNESS_MIMO_PATH``: absolute path to the ``mimo`` binary. ``None`` →
  search ``PATH``.
- ``HARNESS_MIMO_GATEWAY_BASE_URL`` / ``HARNESS_MIMO_GATEWAY_API_KEY``: optional
  OpenAI-compatible gateway creds for the non-free (xiaomi/provider) path,
  exported into the MiMo subprocess env as ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY``.
  Omitted on the free ``mimo/mimo-auto`` channel (needs no key).
"""

from __future__ import annotations

import os

from fastapi import FastAPI

from omnigent.inner.executor import Executor
from omnigent.inner.mimo_executor import MimoExecutor
from omnigent.runtime.harnesses._executor_adapter import ExecutorAdapter

_ENV_MODEL = "HARNESS_MIMO_MODEL"
_ENV_CWD = "HARNESS_MIMO_CWD"
_ENV_PATH = "HARNESS_MIMO_PATH"
_ENV_GATEWAY_BASE_URL = "HARNESS_MIMO_GATEWAY_BASE_URL"
_ENV_GATEWAY_API_KEY = "HARNESS_MIMO_GATEWAY_API_KEY"
# Path where the executor writes the turn's tool calls + native usage so the
# out-of-sandbox OmnigentSession can surface them to BenchFlow's trajectory.
_ENV_TRACE = "HARNESS_MIMO_TRACE"
# Fixed default trace path, shared verbatim with OmnigentSession. Omnigent's
# `run` daemon spawns the harness with the DAEMON's env, NOT the `omnigent run`
# CLI invocation's env (the same reason omnigent routes creds via a config FILE,
# not env) — so HARNESS_MIMO_TRACE set on the CLI line does NOT reach here.
# Defaulting both sides to one fixed sandbox-local path makes the bridge work
# without env propagation; it's safe because each rollout owns its sandbox (one
# session per sandbox) and the session truncates it before every turn.
DEFAULT_TRACE_PATH = "/tmp/omnigent-mimo-trace.json"


def _build_mimo_subprocess_env() -> dict[str, str]:
    """Translate the optional gateway creds into MiMo's OpenAI-compatible env.

    MiMo (an OpenCode fork) reads ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY`` for
    its OpenAI-compatible provider. Empty on the free ``mimo/mimo-auto`` path.
    """
    env: dict[str, str] = {}
    base_url = os.environ.get(_ENV_GATEWAY_BASE_URL, "").strip()
    api_key = os.environ.get(_ENV_GATEWAY_API_KEY, "").strip()
    if base_url:
        env["OPENAI_BASE_URL"] = base_url
    if api_key:
        env["OPENAI_API_KEY"] = api_key
    return env


def _build_mimo_executor() -> Executor:
    """Construct a :class:`MimoExecutor` from ``HARNESS_MIMO_*`` env (lazy)."""
    return MimoExecutor(
        # cwd reaches the daemon-spawned harness via the inherited process cwd
        # (the session `cd /app && omnigent run …`), so os.getcwd() is the
        # workspace even though HARNESS_MIMO_CWD env may not propagate.
        cwd=os.environ.get(_ENV_CWD) or os.getcwd(),
        # model reaches the executor via `omnigent run --model` →
        # request.model_override → run_turn's config.model, not this env.
        model=os.environ.get(_ENV_MODEL) or None,
        mimo_path=os.environ.get(_ENV_PATH) or None,
        env=_build_mimo_subprocess_env(),
        # Fixed default (see DEFAULT_TRACE_PATH): the env does not propagate to
        # the daemon-spawned harness, so the path must be agreed out-of-band.
        trace_path=os.environ.get(_ENV_TRACE) or DEFAULT_TRACE_PATH,
    )


def create_app() -> FastAPI:
    """Build the MiMo harness's FastAPI app (required harness-contract entrypoint)."""
    adapter = ExecutorAdapter(executor_factory=_build_mimo_executor)
    return adapter.build()

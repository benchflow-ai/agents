"""Register the non-ACP Databricks Omnigent ``pi`` agent with BenchFlow.

This is the out-of-core equivalent of an entry in benchflow's own
``agents/registry.py``, defined through the supported ``register_agent``
extension point so the integration lives in this repo instead of the framework.
Importing the package registers ``omnigent-pi`` with ``protocol="session-factory"``
and a ``session_factory`` entrypoint that the kernel's non-ACP CONNECT branch
resolves to :class:`omnigent.agent.OmnigentAgent`. ACP stays the default; this
is purely additive.

Requires the session-factory seam (see README "Requirements")
-------------------------------------------------------------
Unlike the ACP agents in this repo, Omnigent rides a **non-ACP** Session path.
That needs a BenchFlow build whose kernel carries the *session-factory seam*:

* ``AgentConfig.session_factory`` field + ``"session-factory"`` in
  ``registry.VALID_PROTOCOLS`` (so ``register_agent`` accepts the protocol), and
* ``rollout.py`` resolving + connecting via the ``session_factory`` entrypoint
  (``_connect_session_factory``).

That seam is **not** in published BenchFlow ``0.6.x``. When it is absent,
:func:`register` logs a clear warning and returns ``None`` instead of crashing
the import — exactly as ``acp-registry`` degrades without its ``acp_model_via_env``
flag. Install against a BenchFlow build that includes the seam to actually run
``omnigent-pi``.

How this adapter runs Omnigent (in-sandbox subprocess, not in-process SDK)
--------------------------------------------------------------------------
Omnigent's runner pins ``starlette<1`` and ships a conflicting FastAPI / litellm
stack, so it cannot be imported into the BenchFlow host process. Instead the
``install_cmd`` provisions Omnigent **inside the sandbox** under an isolated
``uv tool`` environment, and :class:`omnigent.session.OmnigentSession` shells
the one-shot ``omnigent run --harness pi -p <text>`` CLI there via
:meth:`Sandbox.exec`. The ``pi`` harness binary
(``@earendil-works/pi-coding-agent``) must also be on PATH for the user that
runs ``omnigent run``.

``install_cmd`` therefore, in the sandbox:

1. bootstraps an isolated Node.js (reuses BenchFlow's ``_NODE_INSTALL``); then
   symlinks ``node``/``npm``/``npx`` into ``/usr/local/bin`` — the ``pi`` CLI is
   a ``#!/usr/bin/env node`` script and omnigent's runner spawns the harness
   from a fresh shell that does not inherit the install shell's PATH, so
   ``node`` must resolve on the bare PATH or ``pi`` never launches (the turn
   then completes no work and writes no file);
2. installs ``tmux`` via the image's package manager — omnigent's runner
   auto-creates a per-conversation REPL terminal and hard-fails without it;
3. installs ``uv`` (curl bootstrap, idempotent);
4. ``uv tool install 'omnigent==0.1.0' --with 'omnigent-client==0.1.0'`` — its
   own venv, isolated from any litellm/starlette-1.x in the image;
5. symlinks the ``omnigent`` binary into ``/usr/local/bin`` so a fresh
   (non-login) ``sandbox.exec`` shell resolves it without PATH gymnastics;
6. installs the ``pi`` CLI globally via npm and symlinks it into
   ``/usr/local/bin`` for the same reason;
7. verifies ``omnigent``/``pi``/``node``/``tmux`` all resolve.

Note: omnigent's *managed* REPL terminal additionally wants ``bwrap``
(bubblewrap) to sandbox itself; that auto-create still logs a non-fatal ERROR
inside the BenchFlow sandbox (double-sandboxing is neither available nor
needed). The ``pi`` harness runs its own shell to do the task work, so this
does not block file writes — verified end-to-end (reward 1.0 on hello-world and
on the real ``citation-check`` research task).

Pin
---
``omnigent`` / ``omnigent-client`` are pinned to ``0.1.0`` — the version
declared in the inspected clone's ``pyproject.toml``. Re-pin to a real PyPI
release tag once published; the SDK version-locks ``omnigent-client ==
omnigent`` so bump both together.
"""

from __future__ import annotations

import logging
import shlex

from benchflow.agents.registry import (
    _BENCHFLOW_NODE_PREFIX,
    _NODE_INSTALL,
    register_agent,
)

logger = logging.getLogger(__name__)

# Pinned release. NOTE: the inspected clone reports 0.1.0 with no git tags;
# confirm the published PyPI tag during live verification and update here.
OMNIGENT_PIN = "0.1.0"

# Dotted "module:callable" entrypoint resolved by the non-ACP CONNECT branch
# (see benchflow.rollout: _resolve_session_factory). Must return an object
# satisfying the Agent Protocol (connect/capabilities).
OMNIGENT_SESSION_FACTORY = "omnigent.agent:build_omnigent_agent"

# npm package that provides the ``pi`` harness CLI binary.
_PI_NPM_PACKAGE = "@earendil-works/pi-coding-agent"

# Install the Omnigent CLI + harness INSIDE the sandbox. Idempotent and
# POSIX-sh clean (the sandbox runs install_cmd under ``sh -c``; /bin/sh is dash
# on Ubuntu — no bash-isms). Binaries are placed in /usr/local/bin so later
# (non-login, non-interactive) ``sandbox.exec`` shells — which do not inherit
# this install shell's PATH — resolve ``omnigent``/``pi``/``node`` on the bare
# default PATH. We do NOT write under /root/.local/bin: setup_sandbox_user does
# not copy that into the sandbox user's home, so a non-root exec user would lose
# the tool. ``uv tool install`` is pointed at /usr/local/bin via ``XDG_BIN_HOME``
# so its shim lands directly in the shared prefix.
OMNIGENT_INSTALL_CMD = (
    "set -e; "
    "export DEBIAN_FRONTEND=noninteractive; "
    # 1) Isolated Node.js (provides node + npm for the pi harness CLI). Its own
    #    bootstrap also ensures curl/ca-certificates are present.
    f"{_NODE_INSTALL}; "
    f'export PATH="{_BENCHFLOW_NODE_PREFIX}/bin:$PATH"; '
    # 1a) Put node/npm/npx on the BARE PATH. The pi harness CLI is a
    #     `#!/usr/bin/env node` script, and omnigent's runner spawns the harness
    #     from a fresh (non-login) shell that does NOT inherit this install
    #     shell's PATH — so `node` must resolve on the default PATH or pi dies
    #     with "/usr/bin/env: 'node': No such file or directory". Symlink the
    #     node toolchain into the shared /usr/local/bin prefix (same rationale as
    #     the `pi`/`omnigent` shims below).
    "mkdir -p /usr/local/bin; "
    "for _b in node npm npx; do "
    f'  if [ -x "{_BENCHFLOW_NODE_PREFIX}/bin/$_b" ]; then '
    f'    ln -sf "{_BENCHFLOW_NODE_PREFIX}/bin/$_b" /usr/local/bin/$_b; '
    "  fi; "
    "done; "
    # 1b) Install tmux. Omnigent's runner auto-creates a per-conversation REPL
    #     terminal (the harness's shell/terminal tool runs inside it) and
    #     hard-fails with "tmux is not installed or not on PATH" otherwise — the
    #     turn then starts but the agent can never run a shell command (so it
    #     never writes a file). Install via the image's package manager.
    "if ! command -v tmux >/dev/null 2>&1; then "
    "  if command -v apt-get >/dev/null 2>&1; then "
    "    apt-get update -qq && apt-get install -y -qq tmux; "
    "  elif command -v dnf >/dev/null 2>&1; then dnf -y install tmux; "
    "  elif command -v apk >/dev/null 2>&1; then apk add --no-cache tmux; "
    "  fi; "
    "fi; "
    "command -v tmux >/dev/null 2>&1 || { echo 'tmux install failed' >&2; exit 1; }; "
    # 2) Install uv (idempotent) and put it on PATH for this shell.
    "if ! command -v uv >/dev/null 2>&1; then "
    "curl -LsSf https://astral.sh/uv/install.sh | sh; "
    "fi; "
    'export PATH="$HOME/.local/bin:$PATH"; '
    "command -v uv >/dev/null 2>&1 || { echo 'uv install failed' >&2; exit 1; }; "
    # 3) Install omnigent in its OWN uv-tool venv (isolated deps: starlette<1),
    #    with the entry-point shim placed directly in the shared /usr/local/bin
    #    (XDG_BIN_HOME) so fresh exec shells resolve it without PATH gymnastics.
    "mkdir -p /usr/local/bin; "
    # --python 3.12: omnigent's dep cel-expr-python only ships cp311–313 wheels
    # (no cp314), so uv's default newest Python (3.14) fails to resolve. Pin 3.12.
    # NOTE: cel-expr-python has no linux-aarch64 wheel — omnigent installs on
    # x86_64 sandboxes (e.g. Daytona) but not arm64 (local Apple-Silicon docker).
    "XDG_BIN_HOME=/usr/local/bin uv tool install --force --python 3.12 "
    f"'omnigent=={OMNIGENT_PIN}' --with 'omnigent-client=={OMNIGENT_PIN}'; "
    # 4) Install the pi harness CLI globally and symlink it into /usr/local/bin
    #    (the npm global bin lives under the isolated node prefix, off the bare
    #    PATH). Resolve the real path defensively before linking.
    f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install -g {shlex.quote(_PI_NPM_PACKAGE)}; "
    f'PI_BIN="{_BENCHFLOW_NODE_PREFIX}/bin/pi"; '
    'if [ ! -x "$PI_BIN" ]; then PI_BIN="$(command -v pi || true)"; fi; '
    'if [ -n "$PI_BIN" ] && [ -x "$PI_BIN" ]; then '
    'ln -sf "$PI_BIN" /usr/local/bin/pi; '
    "fi; "
    # 5) Verify the toolchain resolves on the bare /usr/local/bin-backed PATH.
    "omnigent --version; "
    "which pi; which node; which tmux"
)


def _session_factory_seam_present() -> bool:
    """True when the installed BenchFlow carries the session-factory seam.

    ``"session-factory" in registry.VALID_PROTOCOLS`` is the single gate: the
    membership, the ``AgentConfig.session_factory`` field, and the rollout
    ``_connect_session_factory`` branch were all added together as one seam, so
    this is a faithful proxy for "can the kernel actually drive this agent".
    Older BenchFlow may lack ``VALID_PROTOCOLS`` entirely — treat any import
    failure as "absent" so this is safe on every version.

    Gating up front (rather than relying on ``register_agent`` to reject an
    unknown protocol) makes behaviour identical across versions: published
    BenchFlow does NOT validate ``protocol`` at registration time, so without
    this gate it would silently register a non-functional ``omnigent-pi``.
    """
    try:
        from benchflow.agents.registry import VALID_PROTOCOLS
    except Exception:
        return False
    return "session-factory" in VALID_PROTOCOLS


def register():
    """Register ``omnigent-pi``; idempotent (re-registration overwrites).

    Returns the created ``AgentConfig`` on success, or ``None`` when the
    installed BenchFlow lacks the session-factory seam (logs a clear warning and
    does NOT register, so importing the package is always safe and never leaves a
    non-connectable agent behind).
    """
    if not _session_factory_seam_present():
        logger.warning(
            "omnigent-pi NOT registered: this BenchFlow build lacks the "
            "session-factory seam. Install against a BenchFlow that has "
            "AgentConfig.session_factory + 'session-factory' in VALID_PROTOCOLS "
            "+ rollout._connect_session_factory. See the omnigent README."
        )
        return None

    config = register_agent(
        name="omnigent-pi",
        description=(
            "Databricks Omnigent `pi` harness, run INSIDE the BenchFlow "
            "sandbox via the one-shot `omnigent run` CLI (non-ACP, "
            "session-factory). Model + credentials are written into the "
            "sandbox at connect() time from the resolved BenchFlow provider "
            "routing."
        ),
        install_cmd=OMNIGENT_INSTALL_CMD,
        # No ACP subprocess: the kernel uses the session_factory instead of
        # launching + ACP-connecting. launch_cmd is kept descriptive only —
        # the actual run is ``omnigent run`` shelled per turn by the session.
        launch_cmd="omnigent run --harness pi",
        protocol="session-factory",
        # The benchmark model is forwarded per turn via ``omnigent run
        # --model`` (read from BENCHFLOW_PROVIDER_MODEL by
        # OmnigentAgent.connect); empty here lets --model /
        # BENCHFLOW_PROVIDER_MODEL drive selection at runtime.
        default_model="",
        api_protocol="openai-completions",
        # Identity passthrough: OmnigentAgent.connect reads BENCHFLOW_PROVIDER_*
        # directly from agent_env (and writes them into the in-sandbox
        # config.yaml), so no agent-native rename is needed. Keeping these in
        # env_mapping documents the contract and keeps the keys in agent_env.
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "BENCHFLOW_PROVIDER_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "BENCHFLOW_PROVIDER_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "BENCHFLOW_PROVIDER_MODEL",
        },
        # Gateway URL/key resolved from the provider at runtime.
        requires_env=[],
        # pi's task-skill discovery dirs. Core's deploy_skills symlinks the run's
        # /skills into these when skills are enabled; without registering them the
        # with/without-skills axis is a no-op (pi never sees the injected skills).
        skill_paths=["$HOME/.pi/agent/skills", "$HOME/.agents/skills"],
    )
    # Non-ACP field — set after construction so the core AgentConfig schema
    # change stays minimal (one optional field; see benchflow registry.py).
    config.session_factory = OMNIGENT_SESSION_FACTORY
    return config

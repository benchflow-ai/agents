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

import base64
import logging
import shlex
from pathlib import Path

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
    )
    # Non-ACP field — set after construction so the core AgentConfig schema
    # change stays minimal (one optional field; see benchflow registry.py).
    config.session_factory = OMNIGENT_SESSION_FACTORY
    return config


# ─────────────────────────────────────────────────────────────────────────────
# omnigent-mimo — MiMo Code (OpenCode fork) as a faithful `--harness mimo`
# ─────────────────────────────────────────────────────────────────────────────
# Omnigent's `--harness` is a CLOSED enum (`OMNIGENT_HARNESSES`) dispatched via a
# hardcoded `_HARNESS_MODULES` dict — there is no plugin/register_harness seam.
# So `omnigent-mimo` is an **install-time overlay**: install stock omnigent, drop
# three new modules into its site-packages `inner/`, and register `"mimo"` in the
# two registries by APPENDING a line to each module (mutating the live
# `_HARNESS_MODULES` dict / rebinding the `OMNIGENT_HARNESSES` frozenset at module
# load — no line-number or sitecustomize fragility, and `uv tool install --force`
# recreates the venv each run so the appends never accumulate). The harness
# subprocess inherits `os.environ` (process_manager._build_harness_spawn_env), so
# `OmnigentSession` passes `HARNESS_MIMO_*` on the `omnigent run --harness mimo`
# line and they reach `mimo_harness.create_app()` with NO patch to omnigent's own
# spawn-env builders (which return None for an unknown harness).
#
# The overlay modules live in this package under `overlay/`; only the
# dependency-free `_mimo_acp.py` is import-tested here. `mimo_executor.py` /
# `mimo_harness.py` import real omnigent internals + fastapi, so they're shipped
# as source and verified by the install-time import assertion + the live run.

# Dotted entrypoint for omnigent-mimo. Distinct from OMNIGENT_SESSION_FACTORY so
# the kernel resolves a factory pinned to harness="mimo" without needing the
# kernel to thread the agent name through.
OMNIGENT_MIMO_SESSION_FACTORY = "omnigent.agent:build_omnigent_mimo_agent"

# npm package providing the `mimo` CLI binary (OpenCode fork). Pinned.
_MIMO_NPM_PACKAGE = "@mimo-ai/cli@0.1.1"

# The overlay modules, deployed into omnigent's site-packages `inner/`.
_OVERLAY_DIR = Path(__file__).parent / "overlay"
_OVERLAY_FILES = ("_mimo_acp.py", "mimo_executor.py", "mimo_harness.py")


def _build_mimo_install_cmd() -> str:
    """Assemble the in-sandbox install command for omnigent-mimo.

    Reuses omnigent-pi's toolchain bootstrap (node on the bare PATH + tmux + uv +
    `uv tool install omnigent`), then layers the MiMo overlay: deploy the three
    `inner/` modules, append the two registry lines (idempotently), provision the
    `mimo` CLI, and assert the registration actually took (fails the install loud
    if omnigent's internals drifted under the pin).
    """
    # Base64-embed each overlay module's source (read at import time from this
    # package), mirroring ai-sdk/harness-mimo's server.mjs deploy.
    deploy_lines = ""
    for name in _OVERLAY_FILES:
        b64 = base64.b64encode((_OVERLAY_DIR / name).read_text().encode()).decode()
        deploy_lines += (
            f'printf %s {shlex.quote(b64)} | base64 -d > "$OMNI_PKG/inner/{name}"; '
        )

    # Append-to-module registry registration (idempotent via grep guard). Each
    # appended statement is its own single-line ``printf`` argument — NEVER an
    # embedded newline inside one quoted arg — because a real ``\n`` inside the
    # printf %s argument does not survive shell transport reliably (it can reach
    # the file as a literal ``\n``, which then SyntaxErrors the patched module).
    harness_modules_line = '_HARNESS_MODULES["mimo"] = "omnigent.inner.mimo_harness"'
    # The two compat statements, appended via one ``printf '\n%s\n%s\n'`` with two
    # separate args (so the newline between them comes from the format, not a
    # newline embedded in an argument).
    compat_stmt1 = 'OMNIGENT_HARNESSES = OMNIGENT_HARNESSES | frozenset({"mimo"})'
    compat_stmt2 = (
        "_OMNIGENT_ACCEPTED_HARNESSES = OMNIGENT_HARNESSES | OMNIGENT_HARNESS_ALIASES"
    )
    # Also register mimo as model-override-capable (its model is routed via env,
    # like the other SDK harnesses) so Omnigent's server-driven sub-agent dispatch
    # (`sys_session_send` with a `model`) accepts a mimo child harness — the
    # single-run BenchFlow path doesn't hit this gate, but a complete harness does.
    model_override_line = '_SDK_MODEL_OVERRIDE_HARNESSES = _SDK_MODEL_OVERRIDE_HARNESSES | frozenset({"mimo"})'

    # Install-time assertion: all THREE registries carry mimo AND the harness
    # module imports cleanly (which exercises mimo_executor + _mimo_acp + the
    # fastapi / ExecutorAdapter wiring inside omnigent's own venv).
    verify_py = (
        "from omnigent.spec._omnigent_compat import OMNIGENT_HARNESSES;"
        "from omnigent.runtime.harnesses import _HARNESS_MODULES;"
        "from omnigent.model_override import harness_supports_model_override;"
        "assert 'mimo' in OMNIGENT_HARNESSES, OMNIGENT_HARNESSES;"
        "assert _HARNESS_MODULES.get('mimo') == 'omnigent.inner.mimo_harness', _HARNESS_MODULES;"
        "assert harness_supports_model_override('mimo'), 'mimo model-override not registered';"
        "import importlib; importlib.import_module('omnigent.inner.mimo_harness');"
        "print('omnigent-mimo overlay OK: mimo registered + harness importable')"
    )

    return (
        "set -e; "
        "export DEBIAN_FRONTEND=noninteractive; "
        # 1) Isolated Node.js (provides node/npm for the mimo CLI) + bare-PATH symlinks.
        f"{_NODE_INSTALL}; "
        f'export PATH="{_BENCHFLOW_NODE_PREFIX}/bin:$PATH"; '
        "mkdir -p /usr/local/bin; "
        "for _b in node npm npx; do "
        f'  if [ -x "{_BENCHFLOW_NODE_PREFIX}/bin/$_b" ]; then '
        f'    ln -sf "{_BENCHFLOW_NODE_PREFIX}/bin/$_b" /usr/local/bin/$_b; '
        "  fi; "
        "done; "
        # 2) tmux — omnigent's managed REPL terminal hard-fails without it.
        "if ! command -v tmux >/dev/null 2>&1; then "
        "  if command -v apt-get >/dev/null 2>&1; then "
        "    apt-get update -qq && apt-get install -y -qq tmux; "
        "  elif command -v dnf >/dev/null 2>&1; then dnf -y install tmux; "
        "  elif command -v apk >/dev/null 2>&1; then apk add --no-cache tmux; "
        "  fi; "
        "fi; "
        "command -v tmux >/dev/null 2>&1 || { echo 'tmux install failed' >&2; exit 1; }; "
        # 3) uv (idempotent).
        "if ! command -v uv >/dev/null 2>&1; then "
        "curl -LsSf https://astral.sh/uv/install.sh | sh; "
        "fi; "
        'export PATH="$HOME/.local/bin:$PATH"; '
        "command -v uv >/dev/null 2>&1 || { echo 'uv install failed' >&2; exit 1; }; "
        # 4) Stock omnigent in its own uv-tool venv. --python 3.12 for
        #    cel-expr-python. **--link-mode=copy is REQUIRED**: uv hardlinks
        #    package files from its shared cache by default, so the overlay's
        #    append-to-installed-module step (7) would otherwise mutate the CACHED
        #    file through the shared inode — poisoning every later install (even
        #    `--force`) with the appended lines. Copy mode gives the venv private
        #    file copies, so the appends touch only this install and `--force`
        #    truly recreates a clean tree each run.
        "mkdir -p /usr/local/bin; "
        "XDG_BIN_HOME=/usr/local/bin uv tool install --force --link-mode=copy --python 3.12 "
        f"'omnigent=={OMNIGENT_PIN}' --with 'omnigent-client=={OMNIGENT_PIN}'; "
        # 5) Locate omnigent's package dir inside the tool venv.
        'OMNI_PY="$(uv tool dir)/omnigent/bin/python"; '
        '[ -x "$OMNI_PY" ] || OMNI_PY="$(uv tool dir)/omnigent/bin/python3"; '
        '[ -x "$OMNI_PY" ] || { echo "omnigent venv python not found" >&2; exit 1; }; '
        'OMNI_PKG="$("$OMNI_PY" -c "import omnigent,os;print(os.path.dirname(omnigent.__file__))")"; '
        '[ -d "$OMNI_PKG/inner" ] || { echo "omnigent inner/ not found at $OMNI_PKG" >&2; exit 1; }; '
        # 6) Deploy the three overlay modules into omnigent/inner/.
        f"{deploy_lines}"
        # 7) Register "mimo" in the THREE registries by appending one line each
        #    (idempotent: skip if already present).
        'HMOD="$OMNI_PKG/runtime/harnesses/__init__.py"; '
        f'grep -q \'_HARNESS_MODULES\\["mimo"\\]\' "$HMOD" || '
        f"printf '\\n%s\\n' {shlex.quote(harness_modules_line)} >> \"$HMOD\"; "
        'CMPT="$OMNI_PKG/spec/_omnigent_compat.py"; '
        'grep -q \'frozenset({"mimo"})\' "$CMPT" || '
        f"printf '\\n%s\\n%s\\n' {shlex.quote(compat_stmt1)} {shlex.quote(compat_stmt2)} >> \"$CMPT\"; "
        'MOVR="$OMNI_PKG/model_override.py"; '
        '[ -f "$MOVR" ] && { grep -q \'_SDK_MODEL_OVERRIDE_HARNESSES | frozenset({"mimo"})\' "$MOVR" || '
        f"printf '\\n%s\\n' {shlex.quote(model_override_line)} >> \"$MOVR\"; }}; "
        # 8) Provision the mimo CLI globally + symlink onto the bare PATH.
        f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install -g {shlex.quote(_MIMO_NPM_PACKAGE)}; "
        f'MIMO_BIN="{_BENCHFLOW_NODE_PREFIX}/bin/mimo"; '
        'if [ ! -x "$MIMO_BIN" ]; then MIMO_BIN="$(command -v mimo || true)"; fi; '
        'if [ -n "$MIMO_BIN" ] && [ -x "$MIMO_BIN" ]; then ln -sf "$MIMO_BIN" /usr/local/bin/mimo; fi; '
        # 9) Verify the whole toolchain + the overlay registration actually took.
        f'"$OMNI_PY" -c {shlex.quote(verify_py)}; '
        "omnigent --version; "
        "which mimo; which node; which tmux"
    )


MIMO_INSTALL_CMD = _build_mimo_install_cmd()


def register_mimo():
    """Register ``omnigent-mimo``; idempotent. Same seam gate as ``omnigent-pi``.

    Returns the created ``AgentConfig`` on success, or ``None`` when the installed
    BenchFlow lacks the session-factory seam (logs a warning; import stays safe).
    """
    if not _session_factory_seam_present():
        logger.warning(
            "omnigent-mimo NOT registered: this BenchFlow build lacks the "
            "session-factory seam (see the omnigent README)."
        )
        return None

    config = register_agent(
        name="omnigent-mimo",
        description=(
            "Databricks Omnigent with MiMo Code (OpenCode fork) as a faithful "
            "`--harness mimo`, run INSIDE the BenchFlow sandbox via the one-shot "
            "`omnigent run` CLI (non-ACP, session-factory). MiMo's own agent loop "
            "drives each turn through an install-time overlay (MimoExecutor over "
            "`mimo acp`); the free `mimo/mimo-auto` channel needs no key."
        ),
        install_cmd=MIMO_INSTALL_CMD,
        launch_cmd="omnigent run --harness mimo",
        protocol="session-factory",
        default_model="",
        api_protocol="openai-completions",
        # MiMo routes via HARNESS_MIMO_* env on the `omnigent run` line (set by
        # OmnigentSession from the resolved provider routing) — identity
        # passthrough, same contract documentation as omnigent-pi.
        env_mapping={
            "BENCHFLOW_PROVIDER_BASE_URL": "BENCHFLOW_PROVIDER_BASE_URL",
            "BENCHFLOW_PROVIDER_API_KEY": "BENCHFLOW_PROVIDER_API_KEY",
            "BENCHFLOW_PROVIDER_MODEL": "BENCHFLOW_PROVIDER_MODEL",
        },
        requires_env=[],
        install_timeout=1800,
    )
    config.session_factory = OMNIGENT_MIMO_SESSION_FACTORY
    return config

"""Register the non-ACP Databricks Omnigent harnesses with BenchFlow.

This is the out-of-core equivalent of an entry in benchflow's own
``agents/registry.py``, defined through the supported ``register_agent``
extension point so the integration lives in this repo instead of the framework.
Importing the package registers one ``omnigent-<slug>`` agent per Omnigent
``--harness`` value (see :data:`HARNESSES`), each with
``protocol="session-factory"`` and a per-harness ``session_factory`` entrypoint
that the kernel's non-ACP CONNECT branch resolves to
:class:`omnigent.agent.OmnigentAgent`. ACP stays the default; this is purely
additive.

Status — only ``omnigent-pi`` is fully worked
---------------------------------------------
``omnigent-pi`` is verified end-to-end (install → connect → ``omnigent run`` →
verifier; reward 1.0). The other 21 harnesses — every canonical ``--harness``
value, including the ``*-native`` drivers — are **listed** so they appear in the
registry the same way: omnigent itself is installed by the shared ``install_cmd``
and each agent is wired to its per-harness ``session_factory``. But each
harness's OWN CLI install (the vendor SDK/CLI, or omnigent's native driver) and
model routing are the NEXT step and are **not yet wired** — the shared
``install_cmd`` only provisions omnigent + node + uv + tmux (+ the harmless
``pi`` CLI). Do not assume a non-pi agent runs until its CLI is provisioned.

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

# Every canonical Omnigent harness, derived from the upstream source of truth
# (github.com/omnigent-ai/omnigent: omnigent/inner/*_harness.py + harness_aliases.py),
# NOT omnigent's README (which lists only a subset). One BenchFlow agent per
# canonical ``--harness`` value — 22 in all, including the ``*-native`` drivers.
# Vendor-SDK/CLI harnesses drive the vendor's own agent; ``*-native`` are
# omnigent's own native drivers (no vendor SDK). Only ``pi`` is fully worked
# today; the rest are listed-not-wired (the harness's own CLI install + model
# routing are the NEXT step).
#
# Each tuple is (slug, harness_value, cli_note):
#   slug          — BenchFlow agent name suffix (``omnigent-<slug>``); the
#                   per-harness session_factory is build_omnigent_<slug_underscored>.
#   harness_value — the literal ``omnigent run --harness <value>`` argument.
#   cli_note      — what the harness's OWN CLI/runtime still needs (NEXT step;
#                   not yet wired for the non-pi harnesses).
HARNESSES: list[tuple[str, str, str]] = [
    (
        "pi",
        "pi",
        "fully worked — pi CLI (@earendil-works/pi-coding-agent) installed + model routing verified",
    ),
    # Vendor SDK / CLI harnesses (each needs its own CLI/SDK in-sandbox):
    (
        "claude",
        "claude-sdk",
        "needs the Claude Code SDK (@anthropic-ai/claude-agent-sdk)",
    ),
    ("codex", "codex", "needs the Codex SDK (@openai/codex-sdk)"),
    ("cursor", "cursor", "needs the cursor CLI"),
    (
        "opencode",
        "opencode-native",
        "needs the opencode binary (canonical `opencode-native`; `opencode` is its alias)",
    ),
    ("hermes", "hermes", "needs the hermes CLI"),
    ("openai-agents", "openai-agents", "needs the OpenAI Agents SDK / python"),
    ("goose", "goose", "needs the goose binary (block/goose)"),
    ("qwen", "qwen", "needs the Qwen Code CLI"),
    ("kimi", "kimi", "needs the Kimi CLI"),
    ("copilot", "copilot", "needs the GitHub Copilot CLI"),
    ("antigravity", "antigravity", "needs Google Antigravity"),
    # omnigent native drivers (no vendor SDK — omnigent runs the agent directly):
    ("pi-native", "pi-native", "omnigent native pi driver"),
    ("claude-native", "claude-native", "omnigent native Claude driver"),
    ("codex-native", "codex-native", "omnigent native Codex driver"),
    ("cursor-native", "cursor-native", "omnigent native Cursor driver"),
    ("hermes-native", "hermes-native", "omnigent native Hermes driver"),
    ("goose-native", "goose-native", "omnigent native goose driver"),
    ("qwen-native", "qwen-native", "omnigent native Qwen driver"),
    ("kimi-native", "kimi-native", "omnigent native Kimi driver"),
    ("antigravity-native", "antigravity-native", "omnigent native Antigravity driver"),
    ("kiro-native", "kiro-native", "Kiro (native-only harness)"),
]

# npm package that provides the ``pi`` harness CLI binary.
_PI_NPM_PACKAGE = "@earendil-works/pi-coding-agent"

# Per-harness CLI provisioning. The shared OMNIGENT_INSTALL_CMD only installs
# omnigent + node + uv + tmux (+ pi). Vendor harnesses additionally need their
# OWN CLI on PATH; that CLI is then pointed at the BenchFlow provider gateway
# (NOT a mounted subscription) by OmnigentAgent.connect, which writes the CLI's
# provider config from the resolved BENCHFLOW_PROVIDER_* — the same gateway
# routing codex-acp / claude-agent-acp use (so the harness runs the benchmark
# model and its usage is captured by the proxy).
#
# install: an extra shell snippet appended to OMNIGENT_INSTALL_CMD (POSIX sh).
_install_codex = (
    "; "
    # Pin codex 0.128.x: it still speaks the OpenAI ``chat`` wire API, which the
    # BenchFlow provider gateway serves. codex >=0.14x is ``responses``-only and
    # 500s against a chat-only gateway. 0.128 is the line codex-acp ships on
    # (``@agentclientprotocol/codex-acp@0.0.45`` → ``@openai/codex@^0.128.0``).
    f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install -g '@openai/codex@~0.128.0'; "
    f'CODEX_BIN="{_BENCHFLOW_NODE_PREFIX}/bin/codex"; '
    'if [ ! -x "$CODEX_BIN" ]; then CODEX_BIN="$(command -v codex || true)"; fi; '
    'if [ -n "$CODEX_BIN" ] && [ -x "$CODEX_BIN" ]; then ln -sf "$CODEX_BIN" /usr/local/bin/codex; fi; '
    "which codex"
)
_install_claude = (
    "; "
    f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install -g @anthropic-ai/claude-code; "
    f'CLAUDE_BIN="{_BENCHFLOW_NODE_PREFIX}/bin/claude"; '
    'if [ ! -x "$CLAUDE_BIN" ]; then CLAUDE_BIN="$(command -v claude || true)"; fi; '
    'if [ -n "$CLAUDE_BIN" ] && [ -x "$CLAUDE_BIN" ]; then ln -sf "$CLAUDE_BIN" /usr/local/bin/claude; fi; '
    "which claude"
)

# slug → extra install snippet. Harnesses absent here use the bare
# OMNIGENT_INSTALL_CMD. Credential/gateway routing for these is written into the
# vendor CLI's config by OmnigentAgent.connect (gateway path, no home_dirs mount).
_HARNESS_SETUP: dict[str, str] = {
    "codex": _install_codex,
    "codex-native": _install_codex,
    "claude": _install_claude,
    "claude-native": _install_claude,
}

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
    this gate it would silently register non-functional ``omnigent-*`` agents.
    """
    try:
        from benchflow.agents.registry import VALID_PROTOCOLS
    except Exception:
        return False
    return "session-factory" in VALID_PROTOCOLS


# Identity passthrough shared by every harness: OmnigentAgent.connect reads
# BENCHFLOW_PROVIDER_* directly from agent_env (and writes them into the
# in-sandbox config.yaml), so no agent-native rename is needed. Keeping these in
# env_mapping documents the contract and keeps the keys in agent_env.
_ENV_MAPPING = {
    "BENCHFLOW_PROVIDER_BASE_URL": "BENCHFLOW_PROVIDER_BASE_URL",
    "BENCHFLOW_PROVIDER_API_KEY": "BENCHFLOW_PROVIDER_API_KEY",
    "BENCHFLOW_PROVIDER_MODEL": "BENCHFLOW_PROVIDER_MODEL",
}


def _description_for(slug: str, value: str, cli_note: str) -> str:
    """Per-agent description — honest about each harness's wiring status."""
    if slug == "pi":
        # The fully-worked one: install + pi CLI + model routing verified.
        return (
            "Databricks Omnigent `pi` harness, run INSIDE the BenchFlow "
            "sandbox via the one-shot `omnigent run` CLI (non-ACP, "
            "session-factory). Model + credentials are written into the "
            "sandbox at connect() time from the resolved BenchFlow provider "
            "routing."
        )
    return (
        f"Databricks Omnigent `{value}` harness (`omnigent run --harness "
        f"{value}`), run INSIDE the BenchFlow sandbox (non-ACP, "
        f"session-factory). STATUS: listed — omnigent installed; the {value} "
        f"harness's own CLI install + model routing are the NEXT step (not yet "
        f"wired) — {cli_note}."
    )


def register():
    """Register every Omnigent harness in :data:`HARNESSES`; idempotent.

    One ``omnigent-<slug>`` agent per harness, each wired to its per-harness
    ``session_factory`` (``omnigent.agent:build_omnigent_<slug>``). Re-running
    overwrites by name. Returns the list of created ``AgentConfig`` objects on
    success, or ``None`` when the installed BenchFlow lacks the session-factory
    seam (logs a clear warning and registers NOTHING, so importing the package is
    always safe and never leaves a non-connectable agent behind).

    Only ``omnigent-pi`` is fully worked end-to-end; the rest are listed (see the
    module docstring + each agent's ``description``) and still need their own CLI
    install + model routing wired before they will run.
    """
    if not _session_factory_seam_present():
        logger.warning(
            "omnigent harnesses NOT registered: this BenchFlow build lacks the "
            "session-factory seam. Install against a BenchFlow that has "
            "AgentConfig.session_factory + 'session-factory' in VALID_PROTOCOLS "
            "+ rollout._connect_session_factory. See the omnigent README."
        )
        return None

    configs = []
    for slug, value, cli_note in HARNESSES:
        # Vendor harnesses append their own CLI install; their gateway routing is
        # written into that CLI's config by connect(). Others use the bare install.
        extra_install = _HARNESS_SETUP.get(slug, "")
        config = register_agent(
            name=f"omnigent-{slug}",
            description=_description_for(slug, value, cli_note),
            # Shared omnigent install (omnigent + node + uv + tmux + pi) plus, for
            # vendor harnesses, that harness's OWN CLI (codex/claude/...).
            install_cmd=OMNIGENT_INSTALL_CMD + extra_install,
            # No ACP subprocess: the kernel uses the session_factory instead of
            # launching + ACP-connecting. launch_cmd is kept descriptive only —
            # the actual run is ``omnigent run`` shelled per turn by the session.
            launch_cmd=f"omnigent run --harness {value}",
            protocol="session-factory",
            # The benchmark model is forwarded per turn via ``omnigent run
            # --model`` (read from BENCHFLOW_PROVIDER_MODEL by
            # OmnigentAgent.connect); empty here lets --model /
            # BENCHFLOW_PROVIDER_MODEL drive selection at runtime.
            default_model="",
            api_protocol="openai-completions",
            env_mapping=dict(_ENV_MAPPING),
            # Gateway URL/key resolved from the provider at runtime.
            requires_env=[],
        )
        # Non-ACP field — set after construction so the core AgentConfig schema
        # change stays minimal (one optional field; see benchflow registry.py).
        config.session_factory = (
            f"omnigent.agent:build_omnigent_{slug.replace('-', '_')}"
        )
        configs.append(config)
    return configs

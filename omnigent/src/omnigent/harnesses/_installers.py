"""Shared vendor-CLI install snippets for harness specs.

A harness ``SPEC``'s ``install`` field is an extra POSIX-sh snippet appended to
``register.OMNIGENT_INSTALL_CMD`` to provision that harness's own CLI on PATH.
The base install already covers omnigent + node + uv + tmux + bubblewrap + the
``pi`` CLI, so only the vendor harnesses that drive a separate CLI need a snippet.
Two harness families share a CLI (codex/-native, claude/-native), so the snippet
is defined once here and referenced from both specs. ``connect()`` then points
that CLI at the BenchFlow provider gateway via the ``~/.omnigent/config.yaml`` it
writes — no vendor subscription mounted.
"""

from __future__ import annotations

from benchflow.agents.registry import _BENCHFLOW_NODE_PREFIX

# The Claude Code CLI (@anthropic-ai/claude-code) — used by claude-sdk +
# claude-native. Installed into the isolated node prefix, then symlinked onto the
# bare /usr/local/bin PATH (a fresh non-login sandbox.exec shell does not inherit
# the install shell's PATH).
INSTALL_CLAUDE = (
    "; "
    f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install -g @anthropic-ai/claude-code; "
    f'CLAUDE_BIN="{_BENCHFLOW_NODE_PREFIX}/bin/claude"; '
    'if [ ! -x "$CLAUDE_BIN" ]; then CLAUDE_BIN="$(command -v claude || true)"; fi; '
    'if [ -n "$CLAUDE_BIN" ] && [ -x "$CLAUDE_BIN" ]; then ln -sf "$CLAUDE_BIN" /usr/local/bin/claude; fi; '
    "which claude"
)

# The Codex CLI (@openai/codex) — used by codex + codex-native. Same
# install-and-symlink pattern as INSTALL_CLAUDE.
INSTALL_CODEX = (
    "; "
    f"{_BENCHFLOW_NODE_PREFIX}/bin/npm install -g @openai/codex; "
    f'CODEX_BIN="{_BENCHFLOW_NODE_PREFIX}/bin/codex"; '
    'if [ ! -x "$CODEX_BIN" ]; then CODEX_BIN="$(command -v codex || true)"; fi; '
    'if [ -n "$CODEX_BIN" ] && [ -x "$CODEX_BIN" ]; then ln -sf "$CODEX_BIN" /usr/local/bin/codex; fi; '
    "which codex"
)

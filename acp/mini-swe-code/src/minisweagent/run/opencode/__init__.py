"""Run mini-swe-agent behind opencode's TUI.

This package implements a thin server that speaks the subset of opencode's
HTTP+SSE protocol the TUI needs, with mini-swe-agent as the agent backend.
Launch with ``mini-opencode`` (or ``python -m minisweagent.run.opencode``),
then attach the real opencode TUI: ``opencode attach <url>``.
"""

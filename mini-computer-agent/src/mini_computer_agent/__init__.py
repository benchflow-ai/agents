"""mini-computer-agent — a minimal computer-use agent.

The computer-use analog of mini-swe-agent: one screenshot -> any vision model ->
one action -> repeat. Pure agent — no ACP/protocol code lives here; benchflow's
ACP layer serves it for benchmarking.

    from mini_computer_agent import run
    run("Open the calculator and compute 2+2", model="gemini/gemini-3.5-flash")
"""

from mini_computer_agent.core import run

__all__ = ["run"]

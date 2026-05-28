"""BenchFlow agent integrations, maintained outside the core framework.

Each integration registers itself with BenchFlow through the public
``benchflow.register_agent`` extension point. Importing this package registers
every bundled agent, so a benchmark run only needs::

    import benchflow_agents  # noqa: F401  (registers mini-swe, ...)

Call :func:`register_all` explicitly if you prefer no import side effects.
"""

from benchflow_agents.mini_swe import register as _register_mini_swe

__all__ = ["register_all"]

_REGISTRARS = (_register_mini_swe,)


def register_all() -> None:
    """Register every bundled agent with BenchFlow (idempotent)."""
    for register in _REGISTRARS:
        register()


register_all()

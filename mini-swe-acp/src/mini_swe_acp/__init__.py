"""mini-swe-agent ⇄ BenchFlow ACP integration.

Registers `mini-swe-agent <https://github.com/SWE-agent/mini-swe-agent>`_ with
BenchFlow through the public ``benchflow.register_agent`` extension point.
Importing this package performs the registration, so a benchmark run only
needs::

    import mini_swe_acp  # noqa: F401  (registers mini-swe and its aliases)

Call :func:`register` explicitly if you prefer no import side effects. The ACP
shim itself (``acp_shim.py``) is deployed into the sandbox by the install
command and speaks ACP on stdio.
"""

from mini_swe_acp.register import register

__all__ = ["register"]

register()

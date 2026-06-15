"""Databricks Omnigent ⇄ BenchFlow integration (non-ACP, session-factory).

Registers the Databricks `Omnigent <https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents>`_
``pi`` harness (``omnigent-pi``) **and** MiMo Code via ``--harness mimo``
(``omnigent-mimo``) with BenchFlow through the public ``benchflow.register_agent``
extension point. Importing this package performs both registrations, so a
benchmark run only needs::

    import omnigent  # noqa: F401  (registers omnigent-pi + omnigent-mimo)

Call :func:`register` / :func:`register_mimo` explicitly if you prefer no import
side effects.

Unlike the ACP agents in this repo, Omnigent rides BenchFlow's **non-ACP**
Session path: the kernel resolves a ``session_factory`` entrypoint and drives
:class:`omnigent.session.OmnigentSession`, which shells the one-shot
``omnigent run --harness pi`` CLI **inside the sandbox**. This requires a
BenchFlow build with the session-factory seam — see the README and
:mod:`omnigent.register`. Without it, :func:`register` logs a warning and
returns ``None`` (the import never crashes).
"""

from omnigent.register import register, register_mimo

__all__ = ["register", "register_mimo"]

register()
register_mimo()

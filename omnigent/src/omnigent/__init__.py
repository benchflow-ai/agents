"""Databricks Omnigent ⇄ BenchFlow integration (non-ACP, session-factory).

Registers the Databricks `Omnigent <https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents>`_
harnesses with BenchFlow through the public ``benchflow.register_agent``
extension point — one ``omnigent-<slug>`` agent per ``--harness`` value
(``pi``, ``claude``, ``codex``, ``cursor``, ``opencode``, ``hermes``,
``openai-agents``; see :data:`omnigent.register.HARNESSES`). Importing this
package performs the registration, so a benchmark run only needs::

    import omnigent  # noqa: F401  (registers the omnigent-* agents)

Call :func:`register` explicitly if you prefer no import side effects; it returns
the list of created ``AgentConfig`` objects.

Status: only ``omnigent-pi`` is fully worked (verified end-to-end). The other
harnesses are **listed** — omnigent itself is installed and each is wired to its
per-harness ``session_factory``, but each harness's own CLI install + model
routing are the NEXT step (not yet wired). See the README + :mod:`omnigent.register`.

Unlike the ACP agents in this repo, Omnigent rides BenchFlow's **non-ACP**
Session path: the kernel resolves a ``session_factory`` entrypoint and drives
:class:`omnigent.session.OmnigentSession`, which shells the one-shot
``omnigent run --harness <value>`` CLI **inside the sandbox**. This requires a
BenchFlow build with the session-factory seam — see the README and
:mod:`omnigent.register`. Without it, :func:`register` logs a warning and
returns ``None`` (the import never crashes).
"""

from omnigent.register import register

__all__ = ["register"]

register()

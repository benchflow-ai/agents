"""Databricks Omnigent ⇄ BenchFlow integration (non-ACP, session-factory).

Registers the Databricks `Omnigent <https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents>`_
harnesses with BenchFlow through the public ``benchflow.register_agent``
extension point — one ``omnigent-<slug>`` agent per harness omnigent **0.3.0**
dispatches (all 22; see :mod:`omnigent.harnesses` for the per-harness spec
registry and :data:`omnigent.register.HARNESSES` for the derived list). Importing
this package performs the registration, so a benchmark run only needs::

    import omnigent  # noqa: F401  (registers the omnigent-* agents)

Call :func:`register` explicitly if you prefer no import side effects; it returns
the list of created ``AgentConfig`` objects.

Status (honest, per harness in ``register._HARNESS_STATUS``): ``omnigent-pi`` +
``omnigent-claude`` are verified end-to-end (reward 1.0); ``omnigent-openai-agents``
runs e2e with ``llm_trajectory`` captured; ``omnigent-codex`` / ``-codex-native``
are gateway-wired but blocked (no gateway ``/v1/responses``); ``claude-native`` /
``qwen`` / ``antigravity`` are gateway-wired (WIP); the remaining vendor harnesses
register + dispatch but need a vendor CLI + API key the gateway does not serve
(``needs-vendor``). Every gateway-wired harness rides one
``~/.omnigent/config.yaml`` provider and omnigent's runner routes it — no
per-harness wiring. See the README + :mod:`omnigent.register`.

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

"""MiMo Code (OpenCode fork) native-ACP CLI as a BenchFlow agent.

Importing this package registers the ``mimo`` agent with BenchFlow via the
public ``register_agent`` extension point — the out-of-core equivalent of the
entry in benchflow's own ``agents/registry.py``. MiMo Code ships a *native*
``mimo acp`` JSON-RPC-over-stdio ACP server (npm ``@mimo-ai/cli``, binary
``mimo``), so — unlike the ai-sdk HarnessAgent packages — there is no JS
``server.mjs`` to deploy; ``mimo acp`` IS the ACP server.
"""

from mimo_acp.register import register

register()

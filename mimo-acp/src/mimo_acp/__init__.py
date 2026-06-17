"""MiMo Code (OpenCode fork) native-ACP CLI as a BenchFlow agent.

Importing this package registers the ``mimo`` agent with BenchFlow via the
public ``register_agent`` extension point — the out-of-core equivalent of the
entry in benchflow's own ``agents/registry.py``. MiMo Code ships a *native*
``mimo acp`` JSON-RPC-over-stdio ACP server (npm ``@mimo-ai/cli``, binary
``mimo``), so — unlike the ai-sdk HarnessAgent packages — there is no JS
``server.mjs`` to deploy; ``mimo acp`` IS the ACP server.

Validated path: with ``acp_model_format="provider/model"`` the launcher writes
a ``mimocode.json`` that redefines the ``openai`` provider to point at
BenchFlow's LiteLLM proxy (``$OPENAI_BASE_URL``), so any gateway-routed model
(e.g. ``deepseek/deepseek-v4-flash``) traverses the proxy and its wire-level raw
LLM is captured in ``trajectory/llm_trajectory.jsonl`` (reward 1.0, live). The
free key-free ``mimo/mimo-auto`` channel also works in-sandbox, but routes to
MiMo's own backend (no proxy, no raw-LLM trajectory). See ``register.py``.
"""

from mimo_acp.register import register

register()

"""Vercel AI SDK 7 HarnessAgent driving MiMo Code's native `mimo acp`.

Importing this package registers the ``ai-sdk-mimo`` agent with BenchFlow via the
public ``register_agent`` extension point. MiMo (an OpenCode fork) is itself a
native ACP agent, so the HarnessAgent runs a thin custom HarnessV1 adapter whose
``doStart`` spawns ``mimo acp`` on the host and bridges its ACP JSON-RPC to the
AI SDK stream — no JS-library wrap (createPi-style) and no WebSocket bridge.
"""

from ai_sdk_harness_mimo.register import register

register()

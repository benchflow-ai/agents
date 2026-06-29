# ai-sdk-opencode

The **[Vercel AI SDK 7 `HarnessAgent`](https://ai-sdk.dev/v7/providers/ai-sdk-harnesses)**
running the **OpenCode** harness (`@ai-sdk/harness-opencode`) as a
[benchflow](https://github.com/benchflow-ai/benchflow) agent over
[ACP](https://github.com/zed-industries/agent-client-protocol). A pure-JS
ACP-over-stdio server (`server.mjs`) wraps `HarnessAgent`; `register.py` wires it
in via the public `register_agent` extension point — sibling to
[`harness-pi`](../harness-pi). opencode bridges to a separate `opencode` process,
so the execution model (in-process just-bash vs a bridge sandbox) is unverified —
the just-bash template from `harness-pi` is kept for now. opencode also ships as a
benchflow-native ACP agent (`opencode`); this is the AI-SDK-`HarnessAgent` variant.

**Status:** Scaffolded — wraps `@ai-sdk/harness-opencode`; runs the AI SDK 7
`HarnessAgent`. Model routing + wire-parity NOT yet verified (next step).

## Dev

```bash
cd ai-sdk/harness-opencode
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"   # benchflow pins an rc litellm
pytest -q                                        # key-free; no sandbox/model needed
ruff check src tests
```

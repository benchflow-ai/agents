# ai-sdk-claude-code

The **[Vercel AI SDK 7 `HarnessAgent`](https://ai-sdk.dev/v7/providers/ai-sdk-harnesses)**
running the **Claude Code** harness, as a BenchFlow ACP agent.

> ⚠️ **Experimental — does NOT run as a BenchFlow eval (yet).** The Claude Code harness
> is **bridge-backed**: it requires a port-exposing **Vercel sandbox**
> (`@ai-sdk/sandbox-vercel` + Vercel creds), which is *remote*. The agent's files
> land in the Vercel sandbox, **not** benchflow's task `/app`, so the verifier
> can't see them; and the local just-bash sandbox (used by
> [`ai-sdk/harness-pi`](../harness-pi)) rejects bridge-backed harnesses. For real
> BenchFlow evaluation of Claude Code, use the native **`claude-agent-acp`** agent.

This package is shipped for **completeness** (full AI SDK harness coverage) and as
a **template** for a Vercel-sandbox `HarnessAgent` ACP server. `server.mjs` is the
same ACP framing + `fullStream`→ACP mapping as `harness-pi`, but builds the agent
with `createClaudeCode()` + `createVercelSandbox()`. `register.py` registers `ai-sdk-claude-code`
(api_protocol `anthropic-messages`).

To make it actually run you'd need: Vercel sandbox credentials wired into
`createVercelSandbox`, and a way to bridge the Vercel sandbox's filesystem to the
benchflow task — which is why the native `claude-agent-acp` (Claude Code CLI directly in
benchflow's sandbox) is the supported path today.

## Dev

```bash
cd ai-sdk/harness-claude-code
uv venv .venv && source .venv/bin/activate
uv pip install --prerelease=allow -e ".[dev]"
pytest -q            # key-free; checks registration wiring + server invariants
ruff check src tests
node --check src/ai_sdk_harness_claude_code/server.mjs
```

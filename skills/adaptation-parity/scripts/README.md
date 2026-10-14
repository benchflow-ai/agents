# adaptation-parity scripts

- **`mock_upstream.mjs`** — capturing, deterministic OpenAI-compatible
  `/chat/completions` mock. Logs every request body to `REQ_LOG`; returns a fixed
  2-turn response (writeFile tool call → final text). Makes an agent's behavior
  deterministic so its upstream requests can be diffed.
- **`acp_capture.mjs`** — drives an agent's ACP launch command (or legacy
  `--server <server.mjs>`) through one prompt
  against the mock, and records the upstream requests + tool calls + file written.
  Use for the **standalone** half of a parity check.
- **`acp_driver.mjs`** — shared bounded ACP client used by `acp_capture.mjs` and
  `acp_smoke.mjs`; handles sessions, permission/fs callbacks, errors, and process
  cleanup.
- **`parity.py`** — the reusable, importable comparator a per-agent pytest calls:
  `assert_wire_parity(expected, actual)`, `compare_outcomes(...)`, `load_capture(path)`,
  plus the explicit `NEUTRAL_DIFFS` allowlist (load-bearing — the rule registry drives
  `normalize_request`).
- **`parity_diff.py`** — a thin CLI over `parity.py`: diffs two upstream-request logs
  (`outside.jsonl` vs `inside.jsonl`); exits non-zero on a real divergence.
- **`scaffold_ai_sdk_agent.py`** — scaffold a new adapter package from `ai-sdk/acp`.

## Wire-parity check (inside == outside)

```bash
# 1) standalone capture
node acp_capture.mjs --server ../../../ai-sdk/acp/src/ai_sdk_acp/server.mjs \
     --out /tmp/outside.jsonl
# Non-Node adapter:
node acp_capture.mjs --launch "python3 /path/to/agent-acp-shim.py" \
     --out /tmp/outside.jsonl

# 2) inside-BenchFlow capture: register the agent and run it on the SAME task,
#    with the LiteLLM gateway forwarding to this mock — i.e. set the provider's
#    base URL to the mock (e.g. DEEPSEEK_BASE_URL=http://127.0.0.1:11500/v1) and
#    start mock_upstream.mjs with REQ_LOG=/tmp/inside.jsonl on the host. Run on
#    sandbox=docker (host-side gateway reaches the host mock over loopback).

# 3) diff
python parity_diff.py /tmp/outside.jsonl /tmp/inside.jsonl
```

`--launch` is passed to `/bin/sh -c`; use only trusted local commands. Use
`--server` for an argv-safe Node script path. Capture mock supports agents using
OpenAI-compatible `/chat/completions`; the agent gets a disposable home directory,
inherited provider routing/auth variables are removed, then supported
OpenAI/OpenRouter/BenchFlow aliases point to mock. `--rpc-timeout <milliseconds>`
bounds each ACP request; failures clean up the disposable home, mock, and agent
process group and exit nonzero. `--out` is truncated before launch; success
requires at least one valid request written by newly started mock.

The model call is what matters for parity; `mock_upstream` removes model
non-determinism so any post-normalization diff is a real, benchflow-introduced
change. Also compare **outcome** (reward, tool sequence, files) on a real run.

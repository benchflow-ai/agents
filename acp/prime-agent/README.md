# prime-agent

[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) — Prime
Intellect's self-improving RLM coding agent (MIT, released 2026-08-06, built on
[pi](https://github.com/badlogic/pi-mono)) — adapted to BenchFlow over ACP.

## How the adaptation works

- **Protocol**: `prime-agent --mode acp` speaks standard ACP over stdio and
  runs in-process (no daemon). One session per connection, which matches
  BenchFlow's one-rollout-per-process ACP client. The agent's single
  model-facing tool is a persistent IPython kernel (`kind: execute` tool calls
  whose `rawInput` carries the cell source).
- **Install** (`install_cmd`): pins the self-hosted npm release tarball
  (`prime-agent-0.7.1.tgz`; the project is not on npmjs) into
  `/opt/benchflow/js-agents`, then pre-provisions the IPython kernel
  environment at `/opt/benchflow/prime-agent/kernel-venv` with uv (Python
  3.11 + ipykernel + dill + the tarball's bundled `prime-agent-runtime` + the
  default RLM package set). Pre-provisioning keeps first tool use off the
  network and — because everything is `/opt`-anchored rather than
  `$HOME`-anchored — works identically under root and under BenchFlow's
  dropped-privilege sandbox user. `fd`/`rg` are preloaded via the package's
  own postinstall hook (non-fatal if that fails; the agent falls back).
- **Model routing** (`launcher.sh` → `/opt/benchflow/bin/prime-agent-acp`):
  Prime Agent has no ACP `set_model`; model selection is env-owned
  (`supports_acp_set_model = false` + `BENCHFLOW_PROVIDER_MODEL` in
  `env_mapping` triggers BenchFlow's model-via-env path). The launcher writes
  a `models.json` declaring one custom OpenAI-compatible provider pointed at
  `BENCHFLOW_PROVIDER_BASE_URL` and passes `--model` at launch. The API key is
  referenced by environment-variable *name* in `models.json`, so no secret is
  written to disk.

## The compat landmine (read before touching the launcher)

Prime Agent auto-detects provider compatibility from the **base URL**
(`resolveCompat` in `packages/ai/src/providers/openai-completions.ts`).
`isNonStandard` matches `baseUrl.includes("deepseek.com")` but not
`provider === "deepseek"`, so behind any proxy base URL the detection flips
and the agent sends the system prompt as the `developer` role (plus a `store`
field). DeepSeek's real API rejects `developer` with a 400 (verified live
2026-08-07); the LiteLLM gateway happens to translate it, which would mask a
real native-vs-benchflow divergence. The launcher therefore mirrors the FULL
effective native compat for DeepSeek model ids explicitly:
`supportsDeveloperRole=false`, `supportsStore=false`,
`maxTokensField=max_completion_tokens`, `thinkingFormat=deepseek`,
`requiresReasoningContentOnAssistantMessages=true`, plus the built-in
catalog's `contextWindow`/`maxTokens`/`thinkingLevelMap`. Wire-parity was
verified request-by-request against a native run (see PR description).

Non-DeepSeek models get a minimal generic entry; extend the launcher's `case`
with other providers' effective compat as needed.

## Regenerating the embedded launcher

`manifest.toml`'s `install_cmd` embeds `launcher.sh` as base64. After editing
`launcher.sh`:

```sh
b64=$(base64 < launcher.sh | tr -d '\n')
# replace the existing blob in manifest.toml's `echo <B64> | base64 -d` stanza
```

## Verification status

- Native (macOS host): `-p` one-shot and `--mode acp` file-write smoke on
  DeepSeek (`deepseek-v4-flash`), plus a 33-tool-call citation-check-prompt
  session against real DeepSeek through a capture proxy.
- BenchFlow/Daytona: see PR description for the citation-check and batch
  results (SkillsBench, `deepseek-v4-pro`).

Known behaviors:
- `-p` print mode reads piped stdin until EOF — always run it with stdin
  closed or redirected from `/dev/null` in drivers.
- Model-written runaway cells (infinite loops) spin inside the IPython kernel;
  BenchFlow's idle/wall-clock watchdogs are the intended backstop, as they are
  for any agent.

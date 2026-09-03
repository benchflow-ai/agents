# OpenClaw ACP shim

This directory owns BenchFlow's OpenClaw ACP adapter. `openclaw_acp_shim.py`
is canonical, readable source. `manifest.toml` installs identical bytes at
`/opt/benchflow/bin/openclaw-acp-shim` and launches that file.

## Supported runtime

- Linux x86_64 or arm64 sandbox
- Python 3.10+
- Node.js 22.20.0
- `openclaw@2026.6.9`
- OpenClaw native providers plus BenchFlow provider configuration passed via
  `BENCHFLOW_PROVIDER_*`

Optional imports from `benchflow.agents.providers` are a compatibility seam.
Shim uses provider-specific metadata when BenchFlow is installed, falling back
to injected env configuration or native model-name heuristics otherwise. Tests
here import source directly and never require installed BenchFlow internals.

## Updating source

Current A/B transport is inline. Edit `openclaw_acp_shim.py`, test it, regenerate
manifest's base64 payload in same PR, then run contract tests. CI requires exact
byte equality between readable source and installed payload. Canonical source
and active deployed bytes must never differ at merge.

Optional artifact transport C is separate. Its update uses two commits in one
PR: source commit `S`, then manifest commit `M` pointing at immutable `S` with
updated SHA-256. At PR head, downloaded bytes, checksum, sibling source, and
installed bytes must match. Reproducible runs pin manifest commit `M`, not
`main`.

## Rollout and rollback

Roll out agents change before deleting BenchFlow's built-in copy. Validate
BenchFlow against local checkout first, then exact merged agents SHA. Roll back
B by reverting BenchFlow to built-in shim. Roll back later agents changes via
`BENCHFLOW_AGENTS_SOURCE=benchflow-ai/agents@<known-good-40-char-SHA>`.

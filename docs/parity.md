# Parity: the same agent in eval and prod

The repo's promise is that an agent **behaves the same** whether driven inside the
BenchFlow eval harness or standalone in production. "It runs in both" is not
enough; the behavior must match. How far that match is checkable depends on the
agent's [adaptation tier](tiers.md): full wire-level behavior-match is the bar for
the **native** and **wired** tiers — the model is gateway-routed, so the raw
upstream request is captured — while **runnable** agents run the model on the
vendor backend with no raw-LLM capture, and can only be checked at the **outcome**
level.

The two checks below map onto the tiers (see [`tiers.md`](tiers.md)): **native** +
**wired** capture the raw-LLM trajectory (gateway proxy) **and** the ACP-trajectory
logs, hence **wire + outcome** parity; **runnable** captures the ACP-trajectory
logs only, hence **outcome** parity only; **catalog**, **vendor-locked**, and
**out-of-scope** are not adapted, so neither check applies. Per-agent verification
evidence — the **Verified** column — now lives in
[`acp-registry/AGENTS.md`](../acp-registry/AGENTS.md). Verify at two levels.

## Wire parity (does the model receive the same request?)

Drive the agent's ACP server against a deterministic, capturing mock upstream —
once **standalone**, once **through BenchFlow's gateway** — and diff the upstream
requests. This is a **native**/**wired**-only check: the gateway proxy is where the
raw-LLM trajectory is captured, so there's something to byte-diff; a **runnable**
agent runs the model on its own/vendor backend, so there's no proxy capture to
diff. Tooling in [`skills/adaptation-parity/scripts`](../skills/adaptation-parity/scripts)
(`acp_capture.mjs` + `parity_diff.py` below; the dir also ships `acp_smoke.mjs`, a
runnable-tier ACP routing/handshake smoke, and `path_wire_parity.py`, a uniform
offline ai-sdk wire-parity check):

```bash
node acp_capture.mjs --server <server.mjs> --out /tmp/outside.jsonl   # standalone
# inside: run the registered agent on the same task with the gateway forwarding
# to the same mock (DEEPSEEK_BASE_URL=http://127.0.0.1:<port>/v1, sandbox=docker)
python parity_diff.py /tmp/outside.jsonl /tmp/inside.jsonl
```

`parity_diff.py` — a thin CLI over the importable
[`parity`](../skills/adaptation-parity/scripts/parity.py) module (`assert_wire_parity` /
`compare_outcomes` / `load_capture`, callable from a per-package pytest) — normalizes
**expected-neutral** differences and PASSes only if the two requests are otherwise
byte-identical. The neutral diffs are an explicit, load-bearing allowlist
(`parity.NEUTRAL_DIFFS`):
- gateway **model-alias** rename — strips only the `benchflow-<provider>-` prefix; the
  canonical upstream model is still compared, so a **different model fails**;
- sandbox **cwd** vs local in the system prompt / tool-result paths — `/app` is matched only
  at a path boundary, and a genuinely different write *directory* under the cwd still differs;
- prompt trailing whitespace (BenchFlow `.strip()`s the instruction);
- `content: null` vs omitted on a tool-call turn (LiteLLM stream re-aggregation);
- the **byte count** in a write **tool-result** (`wrote N bytes`) — scoped to tool-result
  content only, so a byte count in assistant prose or tool-call arguments is **not** masked.

Anything else — a changed sampling param, a reshaped tool schema, a dropped field
the model conditions on — is a real divergence and a FAIL.

## Outcome parity (does it do the same thing?)

Run the same task inside and standalone; compare reward, tool sequence, and files
produced. Token counts differ within model sampling non-determinism — that is *not*
a divergence. For **runnable** agents this is the *only* verification available —
there's no wire capture to fall back from — and since a vendor-backed agent runs
the model on a nondeterministic upstream, the match is correspondingly looser
(expect the reward and broad tool sequence to agree, not an exact trace).

## The honesty bar

> Toy tasks (a single file write) pass trivially and prove almost nothing. **Real
> eval workloads — input files, real toolchains (`pytest`, network), skills — are
> what expose gaps.** Run **many tasks, of more variants** (real SkillsBench tasks,
> not synthetic toys), end-to-end. Record what you ran and what failed, plainly. Do
> not call an agent "parity-verified" beyond the exact tasks you ran it on.

Example of why this matters: `ai-sdk/harness-pi` passes a hello-world file task but
fails the real SkillsBench `citation-check` task — the agent can't see the task's
input file (the just-bash sandbox FS is isolated from where BenchFlow places task
files). A toy task would never have surfaced that.

# 0002 — Vanilla equivalence via wire-parity against a recorded standalone fixture

- Status: Accepted (design grilling 2026-06-17)
- Deciders: Yimin (repo owner)
- Relates to: [0001](0001-unified-agent-contract.md)

## Context

The whole point of hosting agents in benchflow is to capture raw-LLM trajectories + token
usage *without changing agent behavior*. We therefore need an assertion that a benchflow-hosted
agent behaves **exactly the same as vanilla**. Two notions existed and disagreed on the
baseline: the VM check compared against benchflow's own in-core `mimo` agent (by-eye
fingerprint: system-prompt sha, toolset, model-id, `usage_source`, reward), while the agents
repo's `docs/parity.md` + `skills/adaptation-parity/` compares against the agent run
**standalone on its native platform** with byte-level wire parity (`parity_diff.py`,
`mock_upstream.mjs`).

## Decision

- **Baseline = vanilla = the agent run standalone on its native platform** (not benchflow's
  in-core agent).
- **Assertion = wire-parity.** Capture the agent's upstream LLM requests standalone via a mock
  upstream and check that in as a **fixture**. The test drives the benchflow-hosted agent
  through the same capture and asserts every upstream request is **byte-identical** to the
  fixture, modulo an explicit **neutral-diff allowlist**: proxy model-alias rename, sandbox
  cwd, prompt trailing whitespace, `content:null`-vs-omitted.
- **Plus outcome parity:** same reward + same tool sequence; **token counts may vary** within
  sampling noise (never an equality condition).
- **Lives as a per-package offline pytest** that runs from the recorded fixture (no live core
  or live standalone run needed in CI).
- **Fixture capture = genuine native standalone.** The fixture is recorded by running the
  agent via its own native entrypoint against the mock upstream with **no benchflow hosting**,
  on a fixed parity task+model: a host process for mimo/ai-sdk; an **isolated container with
  its own deps** for omnigent (whose native platform *is* a container). One-time per agent,
  checked in. Not "sandbox-vanilla" (same image minus injection) and not a hand-derived shape —
  both weaker baselines were rejected.

## Consequences

- Generalizes the agents repo's existing parity harness into the canonical, reusable
  per-platform test — the literal "exact same" guarantee.
- Each new agent ships its recorded vanilla fixture; equivalence is enforced in CI offline.
- The neutral-diff allowlist is an explicit, reviewed artifact — drift outside it fails.
- Pairs with the runtime fail-closed capture (ADR 0001): pre-merge parity proves behavior is
  identical; runtime `usage_tracking=required` guarantees capture didn't silently regress.

## Alternatives considered

- **Fingerprint parity only** (system-prompt sha + toolset + model-id + `usage_source` +
  reward; tokens within N%). Kept as an optional cheap runtime canary, but rejected as the
  primary gate: it catches gross drift (e.g. PR8's extra `workflow` tool) but not subtler
  payload differences.
- **Both, layered.** Reasonable extension (wire-parity gate + runtime fingerprint canary), but
  the wire-parity fixture test is the canonical assertion; the canary is additive, not
  required.
- **Baseline = in-core agent.** Rejected: couples the test to a core artifact and isn't the
  "vanilla platform" the requirement names.

# Adaptation tiers — what "adapted" means, and what BenchFlow tracks

Not every agent can be benchmarked the same way. This repo classifies every agent
along one axis: **how faithfully can BenchFlow host it** — can it create the
experiment, launch the agent, and track the run's logs, and *how much* of the run
does it capture?

The bar for adaptation is deliberately set at its **floor**:

> **BenchFlow can create the task environment, launch the agent in it, and track
> the run's logs.**

Everything above that floor is a question of *what gets captured*. The tiers name
the answer. They are defined once, in code
([`acp-registry/src/acp_registry/catalog.py`](../acp-registry/src/acp_registry/catalog.py)),
and the live per-agent classification is generated into
[`acp-registry/AGENTS.md`](../acp-registry/AGENTS.md).

## The two things BenchFlow can track

A hosted run produces up to **two** trajectories. Which ones BenchFlow captures is
what separates the tiers:

- **Raw-LLM trajectory** — the actual upstream model requests/responses + token
  usage, reconstructed at BenchFlow's **LiteLLM gateway proxy**. Captured *only*
  when the agent routes its model calls through that gateway (the agent reaches
  *only* the proxy; `usage_tracking=required` fails the run closed on a capture
  miss). This is the faithful, model-enforced signal — it makes the benchmark's
  model authoritative and the usage exact.
- **ACP-trajectory logs** — the agent's own event stream over ACP (messages,
  thoughts, tool calls, results, reward, finish reason), captured by BenchFlow
  driving the agent over the protocol. Available for any agent BenchFlow can
  launch and drive — independent of where the model actually runs.

## The six tiers

Ordered most-actionable first; the badges match
[`AGENTS.md`](../acp-registry/AGENTS.md).

| Tier | What it means | Raw-LLM (proxy) | ACP logs |
|---|---|:---:|:---:|
| ✅ **wired** | Registered here; routes the model through BenchFlow's gateway **by construction** (confirmed env vars + a model id format BenchFlow can emit). | ✅ | ✅ |
| 🏃 **runnable** | Installs + launches headless in a BenchFlow task env; ACP handshake verified. The model runs on the agent's **own/vendor backend**, so it is *not* gateway-enforced. Executable, **not** a faithful model-enforced eval. | ❌ | ✅ |
| 📋 **catalog** | BYO-redirectable in principle but not yet wired; each entry records the exact **next step** — a config-file writer, a binary/uvx installer, a model-id fix, or (as for the sole current member, `kimi`) why it's hard-blocked (mandatory OAuth). | — | — |
| 🟦 **native** | BenchFlow already ships it as a built-in (`--agent <id>`). Gateway-routed like wired; listed so the registry mapping is complete. We don't shadow it. | ✅ | ✅ |
| 🔒 **vendor-locked** | Authenticates only to its vendor's backend (no arbitrary base URL), so BenchFlow can't enforce the benchmark's model or capture usage. | ❌ | — |
| ➖ **out-of-scope** | Not a single LLM coding/eval agent (e.g. an agent marketplace). | — | — |

**wired** and **native** clear the full bar — BenchFlow creates the experiment,
routes the model, and captures *both* trajectories. **runnable** clears only the
floor — BenchFlow creates the experiment and captures the **ACP-trajectory logs
only**; the raw-LLM proxy is not captured because the model is the vendor's, not
ours (vendor-backed agents need their own creds at eval time). **catalog**,
**vendor-locked**, and **out-of-scope** are *not adapted* — catalog is a wiring
to-do with a recipe; the other two can't meet the bar at all.

## Which parity check applies

The tier determines which equivalence claim is even *possible* — see
[parity.md](parity.md):

- **wired / native** — both **wire parity** (the upstream request is byte-identical
  inside-BenchFlow vs. standalone, modulo the neutral-diff allowlist) **and**
  outcome parity. This is the "the agent you ship is the agent you benchmark"
  guarantee, verified at the wire.
- **runnable** — **outcome parity only** (same reward + tool sequence). With no
  raw-LLM capture there is nothing to byte-diff, and the vendor backend is
  nondeterministic, so the match is correspondingly looser. No wire-parity claim
  is made for this tier.

## The live classification

Counts drift as agents get wired; **don't hard-code them here**. The authoritative,
per-agent table — id, license, tier, the exact wiring recipe, and the recorded
verification for each — is generated from the catalog into
[`acp-registry/AGENTS.md`](../acp-registry/AGENTS.md). At the time of writing
(registry snapshot `v1.0.0`):

**wired 13 · runnable 14 · catalog 1 · native 6 · vendor-locked 1 · out-of-scope 1**
— 36 agents total.

The 33 registry agents that adapt (13 wired + 14 runnable + 6 native) ship a
declarative [`acp/<id>/manifest.toml`](../acp); the catalog / vendor-locked /
out-of-scope agents do not (they're recorded in the catalog for a complete mapping,
not installed). `acp-registry.register()` installs the **wired** agents; **runnable**
agents are discovered by BenchFlow via the `acp/<id>/manifest.toml` loader and are
*not* installed by `register()`.

## Moving an agent up a tier

- **catalog → wired** — ship whatever the recipe names: a launch-time config-file
  writer, a binary/uvx install path, or the `acp_model_via_env` flag for agents
  that validate model ids against their own catalog. Flip `status` to `wired` in
  [`catalog.py`](../acp-registry/src/acp_registry/catalog.py) and verify routing.
- **runnable → wired** — find a headless way to point the agent's model at an
  arbitrary base URL + key + model (so BenchFlow's gateway becomes authoritative).
  Several runnable agents are vendor-backed by design and can't make this jump.
- After any change, regenerate the table
  (`python acp-registry/scripts/gen_agents_md.py > acp-registry/AGENTS.md`) — the
  `acp-registry` CI job's freshness check fails if `AGENTS.md` is stale — and
  re-verify with the [adaptation-parity skill](../skills/adaptation-parity).

## The honesty bar

> A tier is a claim about **plumbing**, not performance. **wired** means "registers
> and routes correctly by construction," **not** "passes real workloads" —
> only agents with a recorded **verification** in `AGENTS.md` have been run
> end-to-end, and only on the exact tasks named. **runnable** means "installs,
> launches, and handshakes," **not** "produces a faithful model-enforced eval."
> The 📋 catalog recipes come from each agent's upstream docs/source, not from a
> run — treat them as tested-on-paper, and verify before trusting.

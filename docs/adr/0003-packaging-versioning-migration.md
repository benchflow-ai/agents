# 0003 — Packaging, manifest schema, versioning, and migration

- Status: Accepted (design grilling 2026-06-17)
- Deciders: Yimin (repo owner)
- Relates to: [0001](0001-unified-agent-contract.md)

The operational decisions that implement the unified contract (ADR 0001).

## Decisions

### Distribution
benchflow-ai/agents is published as a **single pip package `benchflow-agents`** that bundles
the whole `agents/<name>/` tree (manifests + shims + skills) as package data. Core's discovery
dir resolves to the installed package's data dir via `importlib.resources`, with a
`BENCHFLOW_AGENTS_DIR` env override pointing at a local checkout for development.
Gives semver releases while preserving the eve "scan a directory" model + a dev escape hatch.
Rejected: git-clone/vendor at a ref (loose versioning); per-agent packages (fragments the tree).

### Manifest schema
The manifest is **minimal and data-only**: `name`, `install_cmd`, `launch_cmd`, `env_mapping`,
`acp_model_format`, `default_model`, `skill_paths`, `home_dirs`, `requires_env`,
`contract_version`. Core validates the parsed manifest against a **versioned published JSON
Schema** and rejects unknown/missing fields. Credential-file emission, subscription auth, and
any config-file writing live in the **shim** (consistent with ADR 0001 §3) — core never
interprets credential/auth directives, keeping it a thin loader.
Rejected: rich manifest mirroring all `AgentConfig` fields (regrows core logic); JSON mirror.

### Versioning
The contract is **SemVer** (`contract_version` per manifest). Core declares a supported range
and at discovery skips/rejects out-of-range manifests with a clear error. The `benchflow-agents`
package additionally pins `benchflow>=N` as a backstop. In-band versioning is required because
the `BENCHFLOW_AGENTS_DIR` dev override bypasses pip pinning.
Rejected: capability flags (fuzzier compat); pip-pin-only lockstep (bypassed by the dev override).

### Migration — strangler-fig
Add the manifest loader **alongside** the existing in-core `AGENTS` dict (core merges both
sources during transition). Migrate incrementally:
1. The **3 mimo agents** first — **PR10 omnigent reshaped as an ACP-shim manifest**, the
   reference implementation.
2. The simple ACP built-ins.
3. The **big Python shims** (openclaw 884L, harvey-lab 748L, deepagents 530L) **last**.

Delete the in-core `AGENTS` dict + the `litellm_runtime` if-ladder **only once everything is
migrated**. No big-bang; both sources coexist; risk is staged; PR10 lands early as the worked
example.
Rejected: big-bang single-PR cutover (all 11 must work at once); new-agents-only (leaves the
decoupling half-done, core never thins).

## Consequences

- `benchflow-agents` and benchflow core release independently within a contract major.
- The JSON Schema is itself a versioned, published artifact (the manifest half of the contract).
- During migration core carries dual discovery; a clear deprecation endpoint (dict+if-ladder
  deletion) is gated on full migration, not a date.
- PR10's path forward is now concrete: reshape omnigent-mimo to `protocol=acp` + a thin
  ACP-stdio shim around `omnigent run` + a `manifest.toml`, as the first migrated agent.

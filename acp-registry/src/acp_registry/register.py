"""Register ACP-registry agents into BenchFlow via the public extension point.

Every ACP-registry agent is already an ACP-over-stdio server, so registration is
thin: install the agent (npm via BenchFlow's own ``_js_agent_install``, or a
per-arch binary download from the vendored registry snapshot), launch it in ACP
mode, and let ``env_mapping`` route its model calls through the gateway.

Only ``status == "wired"`` agents are registered — those whose provider profile
routes correctly *by construction* AND have been verified to run (see
``catalog.py``). The ``catalog`` tier is intentionally not registered: each such
agent still needs something this package doesn't do for it yet (a config-file
writer, a uvx bootstrap, a model-id format BenchFlow can't emit, or a
proprietary/gated install), and shipping an install command we can't stand behind
would be worse than a precise recipe. The recipes live in the catalog so wiring
each one later is a one-spec change.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from benchflow.agents.registry import (
    AGENTS,
    _BENCHFLOW_JS_AGENT_PREFIX,
    _BENCHFLOW_NODE_PREFIX,
    _js_agent_install,
    _js_agent_launch,
    register_agent,
)

from .catalog import BINARY, AcpAgent, wired_agents

logger = logging.getLogger(__name__)

# Where binary agents are installed in the sandbox (parallel to BenchFlow's own
# /opt/benchflow/{node,bin} prefixes, kept out of the task image's runtime).
_BIN_PREFIX = "/opt/benchflow/acp"
_SNAPSHOT = json.loads(
    (Path(__file__).parents[2] / "registry.snapshot.json").read_text()
)
_BY_ID = {a["id"]: a for a in _SNAPSHOT["agents"]}


def _binary_linux_urls(registry_id: str) -> tuple[str, str]:
    """(x86_64, aarch64) Linux release URLs from the vendored registry snapshot."""
    binary = _BY_ID[registry_id]["distribution"]["binary"]
    x86 = binary.get("linux-x86_64", {}).get("archive", "")
    arm = binary.get("linux-aarch64", {}).get("archive", "")
    if not x86:
        raise ValueError(f"{registry_id}: no linux-x86_64 binary in snapshot")
    return x86, arm


def _extract_cmd(archive: str, dest: str) -> str:
    """Shell to extract a downloaded archive into dest, by file extension."""
    if archive.endswith(".tar.gz") or archive.endswith(".tgz"):
        return f'tar -xzf "$BF_ARCHIVE" -C {dest}'
    if archive.endswith(".tar.bz2"):
        return f'tar -xjf "$BF_ARCHIVE" -C {dest}'
    if archive.endswith(".zip"):
        return f'unzip -o -q "$BF_ARCHIVE" -d {dest}'
    # No extension / raw binary: move it into place as the cmd basename.
    return f'cp "$BF_ARCHIVE" {dest}/'


def _binary_install(spec: AcpAgent) -> str:
    """Download + extract the per-arch Linux release into the sandbox."""
    x86, arm = _binary_linux_urls(spec.registry_id)
    dest = f"{_BIN_PREFIX}/{spec.registry_id}"
    bin_path = f"{dest}/{spec.bin_name}"
    arm_branch = f'arm64) U="{arm}";; ' if arm else ""
    return (
        "set -e; export DEBIAN_FRONTEND=noninteractive; "
        "( command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1 && "
        "  command -v bzip2 >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1 || "
        "  (apt-get update -qq && apt-get install -y -qq "
        "   curl ca-certificates tar bzip2 xz-utils unzip) ); "
        'A=$(uname -m); case "$A" in '
        f'x86_64|amd64) U="{x86}";; '
        f"aarch64|{arm_branch}"
        '*) echo "no binary for $A" >&2; exit 1;; esac; '
        f'mkdir -p {dest}; curl -fsSL "$U" -o "$BF_ARCHIVE"; '
        f"{_extract_cmd(x86, dest)}; "
        f"chmod +x {bin_path} 2>/dev/null || true; "
        f"[ -x {bin_path} ]"
    ).replace("$BF_ARCHIVE", "/tmp/bf-acp-archive")


def _launch_env_prefix(spec: AcpAgent) -> str:
    """`KEY=value ` prefix from launch_env. Values are controlled (a provider
    name, a fixed path, or a $BENCHFLOW_PROVIDER_* reference for shell expansion),
    so they are intentionally NOT quoted."""
    return "".join(f"{k}={v} " for k, v in spec.launch_env.items())


def _install_cmd(spec: AcpAgent) -> str:
    if spec.distribution == BINARY:
        return _binary_install(spec)
    cmd = _js_agent_install(spec.bin_name, spec.package)
    if spec.npm_extra:
        # Some agents lazily import a provider SDK the npm pkg doesn't bundle
        # (e.g. deepagents -> @langchain/openai). Install it into the same prefix.
        pkgs = " ".join(spec.npm_extra)
        cmd += (
            f" && {_BENCHFLOW_NODE_PREFIX}/bin/npm install -g --prefix "
            f"{_BENCHFLOW_JS_AGENT_PREFIX} {pkgs} --no-audit --no-fund >/dev/null 2>&1"
        )
    return cmd


def _launch_cmd(spec: AcpAgent) -> str:
    if spec.distribution == BINARY:
        dest = f"{_BIN_PREFIX}/{spec.registry_id}"
        cmd = f"cd {dest} && {_launch_env_prefix(spec)}./{spec.bin_name}"
        return f"{cmd} {spec.acp_args}".rstrip()
    # npx: launch through BenchFlow's isolated JS wrapper (no env prefix — the
    # catalog invariant forbids launch_env on npx wired agents).
    return _js_agent_launch(spec.bin_name, spec.acp_args)


def _register_spec(spec: AcpAgent) -> None:
    cfg = register_agent(
        name=spec.registry_id,
        install_cmd=_install_cmd(spec),
        launch_cmd=_launch_cmd(spec),
        protocol="acp",
        api_protocol=spec.api_protocol,
        env_mapping=dict(spec.env_mapping),
        acp_model_format=spec.acp_model_format,
        supports_acp_set_model=spec.supports_acp_set_model,
        # Required key is inferred from --model at runtime (e.g. DEEPSEEK_API_KEY);
        # the agent only ever sees the gateway/provider key via env_mapping.
        requires_env=[],
        description=spec.summary,
    )
    if not spec.supports_acp_set_model:
        # The model is delivered out-of-band (env_mapping, a launch flag, or a
        # config file) — NOT via ACP set_model — so BenchFlow must not drive it
        # over ACP. Many ACP agents advertise a "model" session config option
        # that validates the value against their *own* model list and reject the
        # benchmark's id (ACP -32603), so capability-first dispatch would
        # otherwise fail at session setup. `acp_model_via_env` skips ACP model
        # configuration entirely. (Only set_model agents keep the ACP path.)
        if hasattr(cfg, "acp_model_via_env"):
            cfg.acp_model_via_env = True
        else:
            logger.warning(
                "%s needs a BenchFlow build with `acp_model_via_env` (the model "
                "is env-owned). On this build BenchFlow will try to set the model "
                "over ACP, which %s rejects (-32603). See acp-registry/AGENTS.md.",
                spec.registry_id,
                spec.registry_id,
            )


def register(*registry_ids: str) -> list[str]:
    """Register wired ACP-registry agents into BenchFlow.

    With no arguments, registers every ``wired`` agent. Pass explicit registry
    ids to register a subset. Never overwrites a BenchFlow built-in: a wired id
    that already exists in ``AGENTS`` (e.g. were one to collide with a native
    agent) is skipped rather than shadowing the built-in.

    Returns the list of agent names actually registered.
    """
    wired = {a.registry_id: a for a in wired_agents()}
    if registry_ids:
        unknown = [rid for rid in registry_ids if rid not in wired]
        if unknown:
            raise KeyError(
                f"not wired (see catalog status): {unknown!r}; "
                f"wired agents are {sorted(wired)!r}"
            )
        targets = [wired[rid] for rid in registry_ids]
    else:
        targets = list(wired.values())

    registered: list[str] = []
    for spec in targets:
        if spec.registry_id in AGENTS:
            # A BenchFlow built-in already owns this name — don't shadow it.
            continue
        _register_spec(spec)
        registered.append(spec.registry_id)
    return registered

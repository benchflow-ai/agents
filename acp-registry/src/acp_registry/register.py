"""Register ACP-registry agents into BenchFlow via the public extension point.

Every ACP-registry agent is already an ACP-over-stdio server, so registration is
thin: install the agent into BenchFlow's isolated Node prefix (reusing the same
``_js_agent_install`` BenchFlow uses for its own ``gemini``/``codex-acp``), launch
it in ACP mode, and let ``env_mapping`` route its model calls through the gateway.

Only ``status == "wired"`` agents are registered — those whose provider profile
routes correctly *by construction* (see ``catalog.py``). The ``catalog`` tier is
intentionally not registered: each such agent needs something this first pass
doesn't ship (a config-file writer, a binary installer, a uvx bootstrap, or a
model-id format BenchFlow can't emit), and shipping an install command we can't
stand behind would be worse than a precise recipe. The recipes live in the
catalog so wiring each one later is a one-spec change.
"""

from __future__ import annotations

import logging

from benchflow.agents.registry import (
    AGENTS,
    _js_agent_install,
    _js_agent_launch,
    register_agent,
)

from .catalog import AcpAgent, wired_agents

logger = logging.getLogger(__name__)


def _install_cmd(spec: AcpAgent) -> str:
    """Bootstrap Node and npm-install the agent into BenchFlow's JS prefix."""
    return _js_agent_install(spec.bin_name, spec.package)


def _launch_cmd(spec: AcpAgent) -> str:
    """Launch the agent in ACP mode through BenchFlow's isolated JS wrapper."""
    # No wired agent sets launch_env (the catalog invariant enforces this), so a
    # plain launch is all that's needed. Constant launch env (e.g. copilot's
    # COPILOT_PROVIDER_TYPE) is recorded on catalog entries as a wiring recipe;
    # whoever wires such an agent should set it via register_agent's contract,
    # not by string-prepending onto a shell command that may start with `export`.
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
    if spec.model_via == "env":
        # The model is delivered via env_mapping (BENCHFLOW_PROVIDER_MODEL ->
        # the agent's model env var), so BenchFlow must NOT also drive it over
        # ACP. Many ACP agents (e.g. qwen-code) advertise a "model" session
        # config option that validates the value against their *own* model list
        # and reject the benchmark's id (ACP -32603), so capability-first
        # dispatch would otherwise fail at session setup. `acp_model_via_env`
        # tells BenchFlow to skip ACP model configuration entirely.
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

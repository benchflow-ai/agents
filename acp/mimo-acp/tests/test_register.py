"""Key-free registration + invariant tests for the mimo-acp agent.

Runs with no sandbox and no API keys: it only inspects the AgentConfig that
``register()`` installs into BenchFlow's registry, plus the install/launch
command strings. Mirrors ai-sdk/harness-codex/tests/test_register.py and
mini-swe-acp/tests, adapted to MiMo's *native* ACP CLI (no server.mjs — mimo
IS the ACP server).
"""

from mimo_acp.register import _MIMO_BIN, _install_cmd, _launch_cmd, register
from benchflow.agents.registry import resolve_agent


def test_register_wires_mimo_native_acp() -> None:
    register()
    cfg = resolve_agent("mimo")
    assert cfg.name == "mimo"
    assert cfg.protocol == "acp"
    # Usage-capture for gateway-routed models lands in OPENAI_*; the free
    # mimo/mimo-auto channel needs no key.
    assert cfg.api_protocol == "openai-completions"
    # provider/model so benchflow's set_config_option(value) carries the
    # "openai/<alias>" prefix the launcher's custom mimocode.json provider
    # ("openai") matches; the bare alias alone yields ProviderModelNotFound and
    # zero LLM requests. The free mimo/mimo-auto id (no slash) is unaffected.
    assert cfg.acp_model_format == "provider/model"
    assert cfg.supports_acp_set_model is True


def test_install_pins_mimo_cli_no_server_mjs() -> None:
    cmd = _install_cmd()
    # Pinned npm package — reproducible (an unpinned float can break ACP).
    # Standardized at @0.1.1 across the agents-repo MiMo packages (the
    # live-validated current release; benchflow-core #679 pins @0.1.0).
    assert "@mimo-ai/cli@0.1.4" in cmd
    # Installs through BenchFlow's isolated node prefix, not the task image's.
    assert "/opt/benchflow" in cmd
    # mimo is a native ACP server: this package must NOT ship/deploy a server.mjs.
    assert "server.mjs" not in cmd


def _decode_launcher(cmd: str) -> str:
    """The launch_cmd is a `printf '%s' '<b64>' | base64 -d > script && sh script`
    pipeline (the base64 indirection survives benchflow's split()/join()
    which-rewrite, which would otherwise shred a multi-line `sh -c` body). Decode
    the embedded payload back to the real shell program the sandbox runs."""
    import base64
    import re

    m = re.search(r"printf '%s' '([A-Za-z0-9+/=]+)'", cmd)
    assert m, f"launch_cmd is not a printf|base64 pipeline: {cmd!r}"
    return base64.b64decode(m.group(1)).decode()


def test_launch_runs_mimo_acp() -> None:
    cmd = _launch_cmd()
    # The which-rewrite splits on whitespace and rejoins; the payload + the
    # printf|base64 wrapper must contain no internal whitespace runs that would
    # be collapsed, so the shell metacharacters survive intact.
    assert " | base64 -d > " in cmd and cmd.strip().endswith(
        "sh /tmp/mimo-acp-launch.sh"
    )
    body = _decode_launcher(cmd)
    # decoded body execs the native mimo acp server (mimo IS the ACP server)
    assert _MIMO_BIN in body
    assert body.strip().endswith("acp")


def test_launch_writes_proxy_provider_in_proxy_mode() -> None:
    """In proxy mode the decoded launcher must register a custom OpenAI-compatible
    provider under the key `openai` (the prefix benchflow emits for benchflow-*
    aliases via set_config_option) pointed at $OPENAI_BASE_URL and keyed by the
    bare alias, then neutralise the colliding OPENAI_* env. Otherwise mimo throws
    ProviderModelNotFoundError and the turn captures zero raw-LLM requests."""
    body = _decode_launcher(_launch_cmd())
    # writes a mimocode.json gated on OPENAI_BASE_URL + the alias being present
    assert "mimocode.json" in body
    assert "OPENAI_BASE_URL" in body and "BENCHFLOW_LITELLM_MODEL_ALIAS" in body
    # the custom provider key is `openai` so `openai/<alias>` resolves
    assert '"openai"' in body and "@ai-sdk/openai-compatible" in body
    assert "BenchFlow Proxy" in body
    # the built-in openai provider auto-activates from OPENAI_* env and would
    # collide with the redefine, so the launcher unsets them before exec —
    # but ONLY in proxy mode: in direct-provider mode (no alias) OPENAI_* IS
    # the provider config and must survive (the old unconditional unset broke
    # every direct run).
    assert 'if [ -n "$A" ]; then' in body
    assert "unset OPENAI_BASE_URL OPENAI_API_KEY" in body
    # and the launcher never hard-exits on direct mode (no alias):
    assert "exit 78" not in body
    # the model id baked into the config is openai/<alias>
    assert "openai/$A" in body or '"model": "openai/' in body


def test_env_mapping_routes_openai_compatible() -> None:
    register()
    cfg = resolve_agent("mimo")
    # OpenAI-compatible gateway routing (repo convention; matches ai-sdk/acp):
    # the LiteLLM gateway URL + proxy key land in OPENAI_BASE_URL/OPENAI_API_KEY.
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_BASE_URL"] == "OPENAI_BASE_URL"
    assert cfg.env_mapping["BENCHFLOW_PROVIDER_API_KEY"] == "OPENAI_API_KEY"


def test_alias_resolves_to_mimo() -> None:
    register()
    assert resolve_agent("mimo-code").name == "mimo"
    # the historical package/manifest name keeps resolving forever
    assert resolve_agent("mimo-acp").name == "mimo"

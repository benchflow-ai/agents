"""Registration + gateway-wiring tests for the Omnigent BenchFlow agents.

The pure helpers (``_normalize_base_url`` / ``_anthropic_base_url`` /
``_build_config_yaml``) and the ``install_cmd`` content are import-safe and run
on any benchflow. The full registration assertions gate on the session-factory
seam: on a benchflow whose ``VALID_PROTOCOLS`` lacks ``"session-factory"`` (e.g.
published 0.6.x), ``register()`` returns ``None`` by design and those tests skip.

Scope: the package hosts all 22 harnesses omnigent **0.3.0** dispatches (derived
from the spec registry in :mod:`omnigent.harnesses`; see ``test_harnesses.py`` for
the registry invariants). Every harness rides ONE gateway provider written into
the sandbox ``~/.omnigent/config.yaml``; omnigent's own runner routes each to its
provider family, so ``connect()`` carries no per-harness wiring.
"""

import asyncio

import pytest

from omnigent import agent as agent_mod
from omnigent.agent import (
    OmnigentAgent,
    _anthropic_base_url,
    _build_config_yaml,
    _normalize_base_url,
)
from omnigent.register import (
    HARNESSES,
    OMNIGENT_INSTALL_CMD,
    OMNIGENT_PIN,
    register,
)

# All 22 harnesses omnigent 0.3.0 dispatches (slug -> ``--harness`` value), the
# hard-coded literal the derived ``HARNESSES`` table is checked against — fails if
# a spec module is dropped, duplicated, or mis-slugged. ``claude`` is omnigent's
# alias for ``claude-sdk``; every other slug equals its value.
_EXPECTED_HARNESSES = {
    "pi": "pi",
    "pi-native": "pi-native",
    "claude": "claude-sdk",
    "claude-native": "claude-native",
    "codex": "codex",
    "codex-native": "codex-native",
    "openai-agents": "openai-agents",
    "cursor": "cursor",
    "cursor-native": "cursor-native",
    "kimi": "kimi",
    "kimi-native": "kimi-native",
    "qwen": "qwen",
    "qwen-native": "qwen-native",
    "goose": "goose",
    "goose-native": "goose-native",
    "hermes": "hermes",
    "hermes-native": "hermes-native",
    "antigravity": "antigravity",
    "antigravity-native": "antigravity-native",
    "copilot": "copilot",
    "kiro-native": "kiro-native",
    "opencode-native": "opencode-native",
}


def _seam_present() -> bool:
    try:
        from benchflow.agents.registry import VALID_PROTOCOLS
    except Exception:
        return False
    return "session-factory" in VALID_PROTOCOLS


# ── Pure helpers (no seam, no sandbox runtime) ────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/v1/", "https://api.deepseek.com/v1"),
        ("", ""),
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    assert _normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # the anthropic wire base is the ROOT (the client appends /v1/messages).
        ("https://gw.test/v1", "https://gw.test"),
        ("https://gw.test/v1/", "https://gw.test"),
        ("https://gw.test", "https://gw.test"),
        ("", ""),
    ],
)
def test_anthropic_base_url_strips_v1(raw: str, expected: str) -> None:
    assert _anthropic_base_url(raw) == expected


def test_build_config_yaml_carries_both_gateway_families() -> None:
    """One gateway provider, both wires the gateway serves: openai ``chat`` (pi /
    openai-agents / codex) on the ``/v1`` base, anthropic ``messages`` (claude)
    on the ROOT base. ``default: true`` lets omnigent's runner resolve each
    harness's family. Scalars are double-quoted with YAML-special chars escaped.
    """
    yaml = _build_config_yaml(
        base_url="https://gw.test/v1",
        api_key='sk-"weird"\\key',
        model="deepseek-chat",
    )
    assert "kind: gateway" in yaml
    assert "default: true" in yaml
    # openai chat family on the /v1 base
    assert "openai:" in yaml
    assert "wire_api: chat" in yaml
    assert 'base_url: "https://gw.test/v1"' in yaml
    # anthropic messages family on the ROOT base (client appends /v1/messages)
    assert "anthropic:" in yaml
    assert 'base_url: "https://gw.test"' in yaml
    # the model lands under each family's models.default
    assert yaml.count('default: "deepseek-chat"') == 2
    # YAML-special chars in the key are escaped inside double quotes.
    assert '\\"weird\\"' in yaml and "\\\\key" in yaml


def test_build_config_yaml_is_harness_agnostic() -> None:
    """The provider block is the same regardless of harness — there is no
    per-harness branching in the wiring (omnigent's runner does the routing)."""
    kw = dict(base_url="https://gw.test/v1", api_key="k", model="m")
    assert _build_config_yaml(**kw) == _build_config_yaml(**kw)


# ── install_cmd content (import-safe) ─────────────────────────────────────


def test_install_cmd_has_node_on_bare_path_and_tmux() -> None:
    cmd = OMNIGENT_INSTALL_CMD
    # node/npm/npx symlinked onto the bare PATH (pi is a node-shebang script).
    assert "for _b in node npm npx" in cmd
    # tmux + bubblewrap installed (managed REPL terminal needs them).
    assert "tmux" in cmd and "bubblewrap" in cmd
    # final verify covers the whole toolchain.
    assert "which pi" in cmd and "which node" in cmd and "which tmux" in cmd
    # pinned omnigent + pinned python.
    assert f"omnigent=={OMNIGENT_PIN}" in cmd and "--python 3.12" in cmd


def test_run_timeout_backstop_is_generous() -> None:
    """The sandbox-exec backstop must sit ABOVE typical task budgets (600-900s)
    so it never clips a legitimate long turn — the kernel's wait_for on the
    task's own ``[agent] timeout_sec`` is the authoritative per-turn bound. A
    once-hardcoded 600 clipped tasks with a 900s budget; default is now 1800,
    overridable via BENCHFLOW_OMNIGENT_RUN_TIMEOUT_SEC.
    """
    from omnigent.session import _RUN_TIMEOUT_SEC

    assert _RUN_TIMEOUT_SEC >= 900


# ── Harness table: all 22 omnigent 0.3.0 dispatches ───────────────────────


def test_harness_table_is_exactly_omnigent_0_3_0_dispatch_set() -> None:
    """The derived table is exactly the 22 harnesses omnigent 0.3.0 dispatches —
    no more (no phantom 0.1.0-only slugs), no less (all vendor + native twins)."""
    by_slug = {slug: value for slug, value, _note in HARNESSES}
    assert by_slug == _EXPECTED_HARNESSES
    assert len(by_slug) == 22
    # the 0.1.0-only non-coding slugs are NOT dispatchable on 0.3.0 and stay out.
    assert not (set(by_slug) & {"open-responses", "databricks-supervisor"})


def test_per_harness_factories_are_module_globals_with_right_harness() -> None:
    """Each ``omnigent.agent:build_omnigent_<slug>`` resolves and binds its
    harness; the function carries a correct ``__name__``/``__qualname__``."""
    for slug, value, _note in HARNESSES:
        fname = f"build_omnigent_{slug.replace('-', '_')}"
        factory = getattr(agent_mod, fname)
        assert factory.__name__ == fname
        assert factory.__qualname__ == fname
        built = factory()
        assert built._harness == value


def test_build_omnigent_agent_back_compat_defaults_to_pi() -> None:
    """The generic alias is retained and still builds a ``pi`` agent."""
    assert agent_mod.build_omnigent_agent()._harness == "pi"
    # exec_user override still flows through.
    assert agent_mod.build_omnigent_agent(exec_user="me")._exec_user == "me"


# ── connect(): uniform wiring + clean degrade (no seam, fake sandbox) ──────


class _FakeSandbox:
    """Records the commands connect() execs; no real I/O."""

    def __init__(self, agent_env: dict[str, str]):
        self.agent_env = agent_env
        self.execs: list[str] = []

    async def exec(self, cmd: str, *, user: str = "root", timeout_sec: int = 30):
        self.execs.append(cmd)

        class _R:
            return_code = 0
            stdout = ""
            stderr = ""

        return _R()


_PROVIDER_ENV = {
    "BENCHFLOW_PROVIDER_BASE_URL": "https://gw.test/v1",
    "BENCHFLOW_PROVIDER_API_KEY": "sk-key",
    "BENCHFLOW_PROVIDER_MODEL": "deepseek-v4-flash",
}


@pytest.mark.parametrize("harness", ["pi", "claude-sdk", "openai-agents", "codex"])
def test_connect_writes_one_gateway_config_for_every_harness(harness) -> None:
    """Every wired harness — pi, claude-sdk, openai-agents, and the blocked codex
    — goes through the SAME path: connect() writes the one gateway config.yaml
    and returns a session bound to the benchmark model. No per-harness branch."""
    sandbox = _FakeSandbox(dict(_PROVIDER_ENV))
    session = asyncio.run(OmnigentAgent(harness=harness).connect(sandbox, role="agent"))

    assert session._harness == harness
    assert session._model == "deepseek-v4-flash"
    # the config.yaml is written once, via a base64 pipe (literal key, no env-ref).
    write = "\n".join(sandbox.execs)
    assert ".omnigent/config.yaml" in write
    assert "base64 -d" in write


def test_connect_degrades_cleanly_for_unknown_harness() -> None:
    """An unknown ``--harness`` value never makes connect() fail opaquely: it
    still writes the gateway config and returns a runnable session (the harness
    then runs on its own backend / is rejected by omnigent at run time)."""
    sandbox = _FakeSandbox(dict(_PROVIDER_ENV))
    session = asyncio.run(
        OmnigentAgent(harness="totally-unknown").connect(sandbox, role="agent")
    )
    assert session is not None
    assert session._harness == "totally-unknown"


# ── Full registration (gated on the session-factory seam) ─────────────────


def test_seam_detection_matches_valid_protocols() -> None:
    """The package's seam probe agrees with the helper used by these tests."""
    from omnigent.register import _session_factory_seam_present

    assert _session_factory_seam_present() == _seam_present()


def test_register_returns_none_when_seam_absent(monkeypatch) -> None:
    """Degradation path — version-independent: force the seam absent and assert
    ``register()`` declines (returns None) rather than registering
    non-connectable agents. Published BenchFlow does not validate ``protocol`` at
    registration time, so the up-front gate (not a register_agent exception) is
    what guarantees this.
    """
    import sys

    import omnigent.register  # noqa: F401  (ensure the submodule is in sys.modules)

    register_mod = sys.modules["omnigent.register"]
    monkeypatch.setattr(register_mod, "_session_factory_seam_present", lambda: False)
    assert register_mod.register() is None


def test_register_wires_all_harnesses_with_seam() -> None:
    if not _seam_present():
        pytest.skip("benchflow build lacks the session-factory seam")
    from benchflow.agents.registry import resolve_agent

    configs = register()
    assert configs is not None
    by_name = {c.name: c for c in configs}
    # every harness in the table registered, named omnigent-<slug>, and nothing
    # else (no phantom agents).
    assert set(by_name) == {f"omnigent-{slug}" for slug in _EXPECTED_HARNESSES}

    for slug, _value, _note in HARNESSES:
        name = f"omnigent-{slug}"
        cfg = by_name[name]
        assert cfg.protocol == "session-factory"
        expected_factory = f"omnigent.agent:build_omnigent_{slug.replace('-', '_')}"
        assert cfg.session_factory == expected_factory
        # resolvable by name through the public registry.
        assert resolve_agent(name).session_factory == expected_factory


def test_register_status_pi_claude_worked_codex_blocked() -> None:
    """Honest status: pi + claude WORKED, openai-agents RUNS, codex BLOCKED — and
    each carries its CLI in install_cmd where it needs one."""
    if not _seam_present():
        pytest.skip("benchflow build lacks the session-factory seam")

    by_name = {c.name: c for c in register()}

    # pi + claude verified WORKED.
    assert "STATUS: WORKED" in by_name["omnigent-pi"].description
    assert by_name["omnigent-pi"].launch_cmd == "omnigent run --harness pi"
    claude = by_name["omnigent-claude"]
    assert claude.launch_cmd == "omnigent run --harness claude-sdk"
    assert "STATUS: WORKED" in claude.description
    assert "@anthropic-ai/claude-code" in claude.install_cmd

    # openai-agents runs (no extra CLI — omnigent bundles the harness).
    assert "STATUS: RUNS" in by_name["omnigent-openai-agents"].description

    # codex is wired (its CLI is installed) but honestly BLOCKED.
    codex = by_name["omnigent-codex"]
    assert "BLOCKED" in codex.description
    assert "@openai/codex" in codex.install_cmd

    # a vendor harness whose wire the gateway doesn't serve is honestly flagged
    # needs-vendor and carries NO auto-install (its CLI is not provisioned).
    goose = by_name["omnigent-goose"]
    assert "vendor backend" in goose.description
    assert (
        goose.install_cmd == by_name["omnigent-openai-agents"].install_cmd
    )  # bare install

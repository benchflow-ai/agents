"""``OmnigentAgent`` — the non-ACP :class:`~benchflow.agents.protocol.Agent` factory.

Declared in the registry (one agent per harness; see :mod:`omnigent.register`)
under ``protocol="session-factory"`` and per-harness ``session_factory``
entrypoints — ``build_omnigent_<slug>`` (with :func:`build_omnigent_agent` kept
as the default-``pi`` back-compat alias). The kernel's non-ACP CONNECT branch
(``benchflow.rollout: _connect_session_factory``) calls
:meth:`OmnigentAgent.connect` instead of ``connect_acp`` and wires the returned
:class:`OmnigentSession` into the trajectory sink.

The agent drives the selected Databricks Omnigent harness (the ``--harness``
value, default ``pi``) by shelling the one-shot ``omnigent run`` CLI **inside
the BenchFlow sandbox** (via :meth:`Sandbox.exec`)
— not by importing the conflicting ``omnigent-client`` SDK in the host process.
``connect`` runs **in-process on the host** but does all its real work in the
sandbox: it writes Omnigent's credential store (``~/.omnigent/config.yaml``)
into the sandbox from the resolved ``agent_env`` (the kernel's per-role provider
routing), then returns a session bound to the sandbox handle.

Model + auth routing
--------------------
The kernel hands ``connect`` an ``agent_env`` dict carrying
``BENCHFLOW_PROVIDER_BASE_URL`` / ``BENCHFLOW_PROVIDER_API_KEY`` /
``BENCHFLOW_PROVIDER_MODEL`` (the resolved provider gateway + model). Those are
written into the in-sandbox ``config.yaml`` as a ``gateway`` provider pointing
``pi`` at an OpenAI-compatible endpoint, with the **literal** API key (an
env-ref does NOT resolve in the daemon-spawned runner). The base URL is
normalized to end with ``/v1``. The model is forwarded to ``omnigent run
--model`` per turn by :class:`OmnigentSession`.
"""

from __future__ import annotations

import base64
import logging
import os
import shlex
from collections.abc import Callable
from typing import Any

from benchflow.agents.protocol import AgentCapabilities
from omnigent.session import OmnigentSession

logger = logging.getLogger(__name__)


def _home_for_user(user: str) -> str:
    """Return the home directory for the sandbox exec user.

    ``root`` → ``/root`` (where ``~`` resolves for the daemon-spawned runner);
    any other user → ``/home/<user>``. Omnigent reads ``$HOME/.omnigent/
    config.yaml`` for the user that runs ``omnigent run``, so the credential
    store must land under the matching home.
    """
    if user == "root" or not user:
        return "/root"
    return f"/home/{user}"


def _normalize_base_url(base_url: str) -> str:
    """Ensure the gateway base URL ends with ``/v1`` (Omnigent's OpenAI wire).

    Omnigent's ``openai`` provider block expects the OpenAI-style ``/v1`` root.
    BenchFlow's resolved provider base URL may or may not include it, so append
    ``/v1`` when absent (tolerating a trailing slash). Empty stays empty.
    """
    url = (base_url or "").rstrip("/")
    if not url:
        return url
    if url.endswith("/v1"):
        return url
    return f"{url}/v1"


def _build_config_yaml(*, base_url: str, api_key: str, model: str) -> str:
    """Render Omnigent's ``~/.omnigent/config.yaml`` from resolved provider env.

    A single ``gateway``-kind provider points the ``pi`` harness at the
    BenchFlow provider endpoint over the OpenAI ``chat`` wire. Values are
    written **literally** (no ``$ENV`` refs): the daemon-spawned runner does not
    expand env-refs, so the literal API key + base URL + model are required.

    All scalar values are double-quoted with the contained ``"`` / ``\\``
    escaped, so an API key or URL with YAML-special characters can't break the
    document. ``model`` is emitted under ``models.default`` (the harness's
    default model) and is also forwarded per turn via ``omnigent run --model``.
    """

    def _q(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    return (
        "providers:\n"
        "  deepseek:\n"  # arbitrary provider key — names the gateway block
        "    kind: gateway\n"
        "    default: pi\n"
        "    openai:\n"
        f"      base_url: {_q(base_url)}\n"
        f"      api_key: {_q(api_key)}\n"
        "      wire_api: chat\n"
        "      models:\n"
        f"        default: {_q(model)}\n"
    )


class OmnigentAgent:
    """The Omnigent agent factory (one per harness) — implements ``Agent``."""

    def __init__(self, *, exec_user: str = "root", harness: str = "pi") -> None:
        # The sandbox user that ``omnigent run`` executes as. ``connect`` writes
        # the credential store under this user's home and the session execs as
        # this user, so the two stay in lockstep.
        self._exec_user = exec_user
        # The canonical ``omnigent --harness`` value this agent drives (e.g.
        # ``pi`` / ``claude-sdk`` / ``codex``). Forwarded to OmnigentSession,
        # which bakes it into the per-turn ``omnigent run --harness <value>``.
        self._harness = harness

    def capabilities(self) -> AgentCapabilities:
        """Declare the non-ACP protocol + multi-turn (nudge) support.

        ``protocol="session-factory"`` matches the wire this agent was
        registered + selected on (see :mod:`omnigent.register`); reporting the
        vendor name here would contradict the registry. ``nudges=True`` — a
        follow-up ``prompt`` runs another ``omnigent run`` turn against the same
        workspace. ``ask_user=False``: the headless one-shot ``omnigent run``
        path never elicits. ``token_logprobs=False`` — usage comes from the
        BenchFlow provider gateway, not the agent.
        """
        return AgentCapabilities(
            protocol="session-factory",
            nudges=True,
            ask_user=False,
            token_logprobs=False,
        )

    async def connect(
        self,
        sandbox: Any,
        role: str,
        *,
        agent_env: dict[str, str] | None = None,
    ) -> OmnigentSession:
        """Write the in-sandbox credential store and return a live session.

        ``sandbox`` is the BenchFlow environment handle and ``role`` the agent
        role; both are accepted for Protocol conformance. The model + gateway
        come from ``agent_env`` — the kernel's resolved per-role agent
        environment (``BENCHFLOW_PROVIDER_BASE_URL`` / ``_API_KEY`` / ``_MODEL``).
        A session-factory agent runs in-process on the host, so the kernel
        passes this dict explicitly rather than injecting it into a subprocess
        env; we still fall back to ``os.environ`` for any key the dict omits
        (host-dev / smoke runs). Reading the model from THIS role's
        ``agent_env`` is what makes a per-role model override reach a fresh
        session on the reviewer/second-scene turn.

        The credential store is written into the sandbox at
        ``<exec-user home>/.omnigent/config.yaml`` so the daemon-spawned
        ``omnigent run`` (executed as ``exec_user`` from ``OmnigentSession``)
        reads the resolved gateway routing with the literal API key.
        """
        env = dict(agent_env or {})

        def _read(name: str) -> str:
            return env.get(name) or os.environ.get(name) or ""

        model = _read("BENCHFLOW_PROVIDER_MODEL")
        base_url = _normalize_base_url(_read("BENCHFLOW_PROVIDER_BASE_URL"))
        api_key = _read("BENCHFLOW_PROVIDER_API_KEY")

        config_yaml = _build_config_yaml(
            base_url=base_url, api_key=api_key, model=model
        )

        home = _home_for_user(self._exec_user)
        config_path = f"{home}/.omnigent/config.yaml"

        # Write the credential store via `exec` (base64-decoded) rather than a
        # sandbox.write_file helper: the concrete sandboxes (DaytonaSandbox etc.)
        # expose `exec`/`upload_file` but not a uniform `write_file`, and a
        # base64 pipe is content-agnostic (the YAML carries an API key, quotes,
        # newlines). mkdir as the exec user so ownership is correct for the
        # daemon-spawned runner.
        b64 = base64.b64encode(config_yaml.encode("utf-8")).decode("ascii")
        await sandbox.exec(
            f"mkdir -p {shlex.quote(home + '/.omnigent')} && "
            f"printf %s {shlex.quote(b64)} | base64 -d > {shlex.quote(config_path)}",
            user=self._exec_user,
            timeout_sec=30,
        )

        logger.info(
            "Omnigent: wrote credential store to %s (model=%r, base_url=%r) "
            "for role=%r as user=%r",
            config_path,
            model,
            base_url,
            role,
            self._exec_user,
        )

        return OmnigentSession(
            sandbox,
            model=model,
            exec_user=self._exec_user,
            harness=self._harness,
        )


def build_omnigent_agent(**kwargs: Any) -> OmnigentAgent:
    """Back-compat ``session_factory`` entrypoint (defaults to the ``pi`` harness).

    Referenced historically from the registry as the dotted path
    ``omnigent.agent:build_omnigent_agent``. Registration now wires each agent to
    its per-harness factory (``build_omnigent_<slug>`` below); this generic alias
    is kept for external callers. Accepts keyword overrides (currently
    ``exec_user`` and ``harness``) for tests and direct programmatic use; the
    production path passes none and runs the ``pi`` harness as ``root`` (the
    default sandbox exec user, whose home is ``/root``).
    """
    return OmnigentAgent(**kwargs)


# Per-harness ``session_factory`` entrypoints. Each is a MODULE-LEVEL global so a
# dotted ``omnigent.agent:build_omnigent_<slug>`` path resolves — the registry
# wires one per harness (see :data:`omnigent.register.HARNESSES`). The function
# name uses underscores because hyphens aren't valid identifiers, so the
# hyphenated ``openai-agents`` harness is reached via ``build_omnigent_openai_agents``.
# slug → canonical ``omnigent --harness`` value:
_HARNESS_VALUES: dict[str, str] = {
    "pi": "pi",
    "claude": "claude-sdk",
    "codex": "codex",
    "cursor": "cursor",
    "opencode": "opencode-native",
    "hermes": "hermes",
    "openai_agents": "openai-agents",
    "goose": "goose",
    "qwen": "qwen",
    "kimi": "kimi",
    "copilot": "copilot",
    "antigravity": "antigravity",
    "pi_native": "pi-native",
    "claude_native": "claude-native",
    "codex_native": "codex-native",
    "cursor_native": "cursor-native",
    "hermes_native": "hermes-native",
    "goose_native": "goose-native",
    "qwen_native": "qwen-native",
    "kimi_native": "kimi-native",
    "antigravity_native": "antigravity-native",
    "kiro_native": "kiro-native",
}


def _make_harness_factory(harness_value: str) -> Callable[..., OmnigentAgent]:
    """Build a ``session_factory`` callable bound to ``harness_value``."""

    def factory(**kwargs: Any) -> OmnigentAgent:
        return OmnigentAgent(harness=harness_value, **kwargs)

    return factory


for _slug, _value in _HARNESS_VALUES.items():
    _name = f"build_omnigent_{_slug}"
    _fn = _make_harness_factory(_value)
    _fn.__name__ = _name
    _fn.__qualname__ = _name
    _fn.__doc__ = (
        f"``session_factory`` entrypoint for the `{_value}` harness "
        f"(omnigent-{_slug.replace('_', '-')}) — returns an OmnigentAgent bound "
        f"to `omnigent run --harness {_value}`. Same keyword overrides as "
        f"build_omnigent_agent (``exec_user``)."
    )
    globals()[_name] = _fn

del _slug, _value, _name, _fn

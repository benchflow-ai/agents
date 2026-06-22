"""Workspace-cwd plumbing: the kernel-resolved rollout workspace must drive
``omnigent run`` instead of a hardcoded ``/app``.

The non-ACP connect path (``connect_session_factory``) injects the kernel's
resolved ``agent_cwd`` into ``agent_env`` as ``BENCHFLOW_AGENT_CWD``;
``OmnigentAgent.connect`` reads it and hands it to ``OmnigentSession``, which
``cd``s there before every ``omnigent run``. When the kernel resolves no cwd
(older core / direct construction) the session keeps the historical ``/app``
default — so a wrong workspace can never silently swallow the agent's output.
"""

import asyncio
from types import SimpleNamespace

from omnigent.agent import build_omnigent_agent
from omnigent.session import _WORKSPACE, OmnigentSession


class _FakeSandbox:
    """Records every ``exec`` command so the test can assert the run cwd."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def exec(self, cmd, *, user=None, timeout_sec=None):  # noqa: ANN001
        self.commands.append(cmd)
        return SimpleNamespace(stdout="done", stderr="", return_code=0)


def _run_cmd(sandbox: _FakeSandbox) -> str:
    """The last recorded command — the ``omnigent run`` turn (mkdir/config is
    written during connect, the run command is issued during prompt)."""
    return sandbox.commands[-1]


def test_connect_threads_agent_cwd_into_omnigent_run() -> None:
    sandbox = _FakeSandbox()
    agent = build_omnigent_agent()

    async def drive() -> None:
        session = await agent.connect(
            sandbox,
            "agent",
            agent_env={
                "BENCHFLOW_PROVIDER_MODEL": "deepseek-v4-flash",
                "BENCHFLOW_PROVIDER_BASE_URL": "http://proxy:4000",
                "BENCHFLOW_PROVIDER_API_KEY": "sk-test",
                "BENCHFLOW_AGENT_CWD": "/workspace/task-root",
            },
        )
        await session.prompt("solve it")

    asyncio.run(drive())
    run_cmd = _run_cmd(sandbox)
    assert run_cmd.startswith("cd /workspace/task-root &&")
    assert "omnigent run --harness pi" in run_cmd


def test_connect_falls_back_to_default_workspace_when_cwd_unset() -> None:
    sandbox = _FakeSandbox()
    agent = build_omnigent_agent()

    async def drive() -> None:
        session = await agent.connect(
            sandbox,
            "agent",
            agent_env={
                "BENCHFLOW_PROVIDER_MODEL": "deepseek-v4-flash",
                "BENCHFLOW_PROVIDER_BASE_URL": "http://proxy:4000",
                "BENCHFLOW_PROVIDER_API_KEY": "sk-test",
            },
        )
        await session.prompt("solve it")

    asyncio.run(drive())
    assert _run_cmd(sandbox).startswith(f"cd {_WORKSPACE} &&")


def test_session_cwd_param_overrides_default() -> None:
    sandbox = _FakeSandbox()
    session = OmnigentSession(sandbox, model="m", cwd="/custom/dir")

    asyncio.run(session.prompt("hi"))
    assert _run_cmd(sandbox).startswith("cd /custom/dir &&")


def test_session_cwd_defaults_to_workspace_when_none() -> None:
    sandbox = _FakeSandbox()
    session = OmnigentSession(sandbox, model="m", cwd=None)

    asyncio.run(session.prompt("hi"))
    assert _run_cmd(sandbox).startswith(f"cd {_WORKSPACE} &&")

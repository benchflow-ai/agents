"""Trackability-bridge tests for the ``omnigent-mimo`` session.

MiMo runs ``usage_tracking=off`` (it rejects the LiteLLM proxy alias), so the
proxy captures zero tokens and the one-shot ``omnigent run -p`` stdout is opaque.
Left unbridged, a mimo run shows zero tokens AND zero tool calls and BenchFlow
nulls the reward as a suspected API error. The session reads the in-sandbox
``MimoExecutor`` trace sidecar to emit ``tool_call`` events (n_tool_calls > 0)
and report native usage via ``latest_usage_totals`` (tokens > 0) — making the
run trackable. These tests drive that path with a fake sandbox (no real omnigent).
"""

import json

import pytest

from omnigent.session import OmnigentSession


class _FakeExecResult:
    def __init__(self, stdout="", stderr="", return_code=0):
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code


class _FakeSandbox:
    """Returns the omnigent-run stdout for the run command and a trace for ``cat``."""

    def __init__(self, *, run_stdout="done", trace_json="", run_return_code=0):
        self._run_stdout = run_stdout
        self._trace_json = trace_json
        self._run_return_code = run_return_code
        self.commands: list[str] = []

    async def exec(self, cmd, user=None, timeout_sec=None):
        self.commands.append(cmd)
        if cmd.strip().startswith("cat "):
            return _FakeExecResult(stdout=self._trace_json)
        if "omnigent run" in cmd:
            return _FakeExecResult(
                stdout=self._run_stdout, return_code=self._run_return_code
            )
        return _FakeExecResult(stdout="")  # omnigent stop / rm / cleanup


def _mimo_session(**kw):
    return OmnigentSession(_FakeSandbox(**kw), model="mimo/mimo-auto", harness="mimo")


# ── usage accumulation ────────────────────────────────────────────────────


def test_latest_usage_totals_is_none_until_a_turn_reports():
    sess = OmnigentSession(_FakeSandbox(), model="m", harness="mimo")
    assert sess.latest_usage_totals() is None


def test_accumulate_usage_is_cumulative():
    sess = OmnigentSession(_FakeSandbox(), model="m", harness="mimo")
    sess._accumulate_usage({"input_tokens": 10, "output_tokens": 3, "total_tokens": 13})
    sess._accumulate_usage({"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})
    assert sess.latest_usage_totals() == {
        "input_tokens": 15,
        "output_tokens": 5,
        "total_tokens": 20,
    }


def test_pi_session_exposes_latest_usage_totals_as_none():
    # omnigent-pi never accumulates → the collector skips it cleanly.
    sess = OmnigentSession(_FakeSandbox(), model="m", harness="pi")
    assert sess.latest_usage_totals() is None


# ── trace ingestion ───────────────────────────────────────────────────────


def test_prompt_emits_tool_calls_and_tracks_usage(_anyio):
    trace = json.dumps(
        {
            "tools": [
                {
                    "id": "t1",
                    "name": "read",
                    "args": {"path": "in.txt"},
                    "result": "contents",
                    "is_error": False,
                },
                {
                    "id": "t2",
                    "name": "write",
                    "args": {"path": "out.txt"},
                    "result": "ok",
                    "is_error": False,
                },
            ],
            "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            "text": "wrote out.txt",
        }
    )
    sandbox = _FakeSandbox(run_stdout="Finished.", trace_json=trace)
    sess = OmnigentSession(sandbox, model="mimo/mimo-auto", harness="mimo")

    _anyio(sess.prompt("do the task"))

    # the omnigent-run command wired the trace env + a stale-trace cleanup
    run_cmd = next(c for c in sandbox.commands if "omnigent run" in c)
    assert "--harness mimo" in run_cmd
    assert "HARNESS_MIMO_TRACE=" in run_cmd and "rm -f" in run_cmd

    steps = sess.steps
    tool_events = [e for e in steps if e.get("type") == "tool_call"]
    assert [e["kind"] for e in tool_events] == ["read", "write"]
    assert tool_events[0]["tool_call_id"] == "t1"
    assert tool_events[0]["status"] == "completed"
    # also mirrored into session.tool_calls — the list the rollout counts
    assert len(sess.tool_calls) == 2
    # tool_calls precede the final agent_message (sensible ordering)
    assert steps.index(tool_events[-1]) < next(
        i for i, e in enumerate(steps) if e.get("type") == "agent_message"
    )
    # native usage surfaced for the rollout's usage collector
    assert sess.latest_usage_totals() == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
    }
    # the trace path is uuid-unique (not a colliding object-id)
    assert "/tmp/omnigent-mimo-trace-" in sess._mimo_trace_path


def test_uuid_trace_paths_are_unique_across_sessions():
    a = OmnigentSession(_FakeSandbox(), model="m", harness="mimo")
    b = OmnigentSession(_FakeSandbox(), model="m", harness="mimo")
    assert a._mimo_trace_path != b._mimo_trace_path


def test_missing_trace_after_success_emits_degraded_warning(_anyio):
    # Run succeeded (rc 0) but no trace written → surface a visible warning rather
    # than silently degrading to zero-activity (which reads as a suspected API error).
    sandbox = _FakeSandbox(run_stdout="done", trace_json="", run_return_code=0)
    sess = OmnigentSession(sandbox, model="mimo/mimo-auto", harness="mimo")
    _anyio(sess.prompt("hi"))
    assert not sess.tool_calls
    assert sess.latest_usage_totals() is None
    assert any(
        e.get("type") == "agent_message" and "trace unavailable" in e.get("text", "")
        for e in sess.steps
    )


def test_nonzero_exit_skips_trace_ingestion(_anyio):
    # A failed run must NOT ingest a (possibly stale) trace — no tool calls/usage
    # attributed to this turn, and `cat` is never even issued for the trace.
    trace = json.dumps(
        {
            "tools": [{"id": "x", "name": "read", "result": "r", "is_error": False}],
            "usage": {"total_tokens": 9},
        }
    )
    sandbox = _FakeSandbox(run_stdout="boom", trace_json=trace, run_return_code=1)
    sess = OmnigentSession(sandbox, model="mimo/mimo-auto", harness="mimo")
    _anyio(sess.prompt("hi"))
    assert not sess.tool_calls
    assert sess.latest_usage_totals() is None
    assert not any(c.strip().startswith("cat ") for c in sandbox.commands)


def test_close_cleans_up_trace_and_creds(_anyio):
    sandbox = _FakeSandbox()
    sess = OmnigentSession(sandbox, model="mimo/mimo-auto", harness="mimo")
    _anyio(sess.close())
    cleanup = next(
        (c for c in sandbox.commands if "rm -f" in c and "mimo.env" in c), None
    )
    assert cleanup is not None
    assert sess._mimo_trace_path in cleanup


def test_pi_prompt_does_not_set_mimo_trace(_anyio):
    sandbox = _FakeSandbox(run_stdout="done")
    sess = OmnigentSession(sandbox, model="deepseek/deepseek-chat", harness="pi")
    _anyio(sess.prompt("hi"))
    run_cmd = next(c for c in sandbox.commands if "omnigent run" in c)
    assert "--harness pi" in run_cmd
    assert "HARNESS_MIMO_TRACE" not in run_cmd
    # pi path never calls `cat` for a trace
    assert not any(c.strip().startswith("cat ") for c in sandbox.commands)


@pytest.fixture
def _anyio():
    """Run a coroutine to completion without an async test framework."""
    import asyncio

    def _run(coro):
        return asyncio.run(coro)

    return _run

"""Unit tests for the pure ACP bridge (:mod:`omnigent.overlay._mimo_acp`).

These run with no Omnigent / FastAPI present: the bridge is dependency-free by
design. A fake ``mimo acp`` server (a small Python script speaking ACP
JSON-RPC over stdio) stands in for the real ``@mimo-ai/cli`` binary so the full
handshake → prompt → ``session/update`` translation → usage → terminal path is
exercised end-to-end, plus the server→client permission auto-allow.
"""

import asyncio
import json as _json
import os
import stat
import sys

import pytest

from omnigent.overlay._mimo_acp import (
    DEFAULT_MODEL,
    MimoAcp,
    map_usage,
    safe_model_alias,
    text_of,
    translate_update,
)

# A standalone fake `mimo acp` server. Invoked as `<this> acp --cwd <dir>` (argv
# ignored). Speaks the same ACP wire shapes the real `mimo acp` does: replies to
# initialize/session.new/session.set_model, and on session/prompt streams text +
# reasoning + a tool_call/tool_call_update pair, fires a server→client permission
# request (which the client must auto-allow or this blocks), then returns the
# prompt result with usage. Deterministic — no model, no network.
_FAKE_MIMO_ACP = r"""#!/usr/bin/env python3
import json, sys

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

def reply(i, result):
    send({"jsonrpc": "2.0", "id": i, "result": result})

def note(update):
    send({"jsonrpc": "2.0", "method": "session/update",
          "params": {"sessionId": "sess-1", "update": update}})

def readmsg():
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return readmsg()
    return json.loads(line)

while True:
    msg = readmsg()
    if msg is None:
        break
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        reply(mid, {"protocolVersion": 1, "agentInfo": {"name": "OpenCode"},
                    "agentCapabilities": {}})
    elif method == "session/new":
        reply(mid, {"sessionId": "sess-1",
                    "models": {"currentModelId": "mimo/mimo-auto"}})
    elif method == "session/set_model":
        reply(mid, {})
    elif method == "session/prompt":
        note({"sessionUpdate": "agent_message_chunk",
              "content": {"type": "text", "text": "Hello "}})
        note({"sessionUpdate": "agent_thought_chunk",
              "content": {"type": "text", "text": "pondering"}})
        note({"sessionUpdate": "tool_call", "toolCallId": "t1",
              "title": "write", "rawInput": {"path": "answer.txt", "content": "42"}})
        note({"sessionUpdate": "tool_call_update", "toolCallId": "t1",
              "title": "write", "status": "completed",
              "content": {"type": "text", "text": "wrote answer.txt"}})
        # Fire a server->client permission request; block for the auto-allow.
        send({"jsonrpc": "2.0", "id": 9001, "method": "session/request_permission",
              "params": {"options": [{"optionId": "allow_once", "name": "Allow"},
                                     {"optionId": "reject", "name": "Reject"}]}})
        perm = readmsg()
        # Record what the client chose so the test can assert auto-allow.
        chosen = (((perm or {}).get("result") or {}).get("outcome") or {}).get("optionId")
        note({"sessionUpdate": "agent_message_chunk",
              "content": {"type": "text", "text": "world (" + str(chosen) + ")"}})
        reply(mid, {"stopReason": "end_turn",
                    "usage": {"inputTokens": 10, "outputTokens": 3, "totalTokens": 13}})
    else:
        if mid is not None:
            reply(mid, {})
"""


@pytest.fixture
def fake_mimo_bin(tmp_path):
    path = tmp_path / "fake-mimo"
    path.write_text(_FAKE_MIMO_ACP)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return str(path)


# ── pure helpers ──────────────────────────────────────────────────────────


def test_text_of_handles_strings_lists_and_blocks():
    assert text_of("hi") == "hi"
    assert text_of({"type": "text", "text": "a"}) == "a"
    assert (
        text_of([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "ab"
    )
    assert text_of({"type": "content", "content": {"type": "text", "text": "x"}}) == "x"
    assert text_of(None) == ""


def test_map_usage_shapes_and_total_fallback():
    assert map_usage({"inputTokens": 5, "outputTokens": 2, "totalTokens": 7}) == {
        "input_tokens": 5,
        "output_tokens": 2,
        "total_tokens": 7,
    }
    # total falls back to input+output when absent
    assert map_usage({"inputTokens": 5, "outputTokens": 2})["total_tokens"] == 7
    assert map_usage(None) == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    assert map_usage({"cachedReadTokens": 4})["cache_read_input_tokens"] == 4


def test_translate_update_each_kind():
    assert translate_update(
        {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": "hi"},
        }
    ) == {"kind": "text", "text": "hi"}
    assert translate_update(
        {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": "t"},
        }
    ) == {"kind": "reasoning", "text": "t"}
    call = translate_update(
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "x",
            "title": "edit",
            "rawInput": {"a": 1},
        }
    )
    assert call == {"kind": "tool_call", "id": "x", "name": "edit", "args": {"a": 1}}
    done = translate_update(
        {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "x",
            "title": "edit",
            "status": "failed",
            "content": {"type": "text", "text": "boom"},
        }
    )
    assert done == {
        "kind": "tool_result",
        "id": "x",
        "name": "edit",
        "result": "boom",
        "is_error": True,
    }
    # in-progress / unknown kinds are skipped
    assert (
        translate_update({"sessionUpdate": "tool_call_update", "status": "in_progress"})
        is None
    )
    assert translate_update({"sessionUpdate": "plan"}) is None


def test_default_model_is_free_channel():
    assert DEFAULT_MODEL == "mimo/mimo-auto"


# ── full ACP drive against the fake server ────────────────────────────────


def test_run_prompt_streams_translated_events_then_complete(fake_mimo_bin, tmp_path):
    async def go():
        client = await MimoAcp.start(
            mimo_bin=fake_mimo_bin,
            cwd=str(tmp_path),
            model="mimo/mimo-auto",
            env=dict(os.environ),
        )
        assert client.acp_sid == "sess-1"
        events = []
        async for ev in client.run_prompt("write 42 to answer.txt"):
            events.append(ev)
        await client.close()
        return events

    events = asyncio.run(asyncio.wait_for(go(), timeout=20))

    kinds = [e["kind"] for e in events]
    # ordering: streamed events precede the single terminal `complete`
    assert kinds[-1] == "complete"
    assert "complete" not in kinds[:-1]
    assert "error" not in kinds

    texts = [e["text"] for e in events if e["kind"] == "text"]
    assert texts[0] == "Hello "
    # the permission auto-allow selected the allow option (echoed by the fake)
    assert any("allow_once" in t for t in texts), texts

    reasoning = [e["text"] for e in events if e["kind"] == "reasoning"]
    assert reasoning == ["pondering"]

    calls = [e for e in events if e["kind"] == "tool_call"]
    assert calls == [
        {
            "kind": "tool_call",
            "id": "t1",
            "name": "write",
            "args": {"path": "answer.txt", "content": "42"},
        }
    ]

    results = [e for e in events if e["kind"] == "tool_result"]
    assert results[0]["id"] == "t1" and results[0]["is_error"] is False

    complete = events[-1]
    assert complete["stop_reason"] == "end_turn"
    assert complete["usage"] == {
        "input_tokens": 10,
        "output_tokens": 3,
        "total_tokens": 13,
    }


def test_run_prompt_surfaces_rpc_error_as_terminal(tmp_path):
    """A server that dies mid-prompt yields a terminal ``error`` event, not a hang."""
    crasher = tmp_path / "crash-mimo"
    crasher.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    line = line.strip()\n"
        "    if not line:\n"
        "        continue\n"
        "    msg = json.loads(line)\n"
        "    m = msg.get('method')\n"
        "    if m == 'initialize':\n"
        "        sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{}})+'\\n'); sys.stdout.flush()\n"
        "    elif m == 'session/new':\n"
        "        sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'sessionId':'s'}})+'\\n'); sys.stdout.flush()\n"
        "    elif m == 'session/prompt':\n"
        "        sys.exit(1)\n"  # die without answering the prompt
    )
    crasher.chmod(crasher.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)

    async def go():
        client = await MimoAcp.start(
            mimo_bin=str(crasher), cwd=str(tmp_path), model=None, env=dict(os.environ)
        )
        events = [ev async for ev in client.run_prompt("hi")]
        await client.close()
        return events

    events = asyncio.run(asyncio.wait_for(go(), timeout=20))
    assert events[-1]["kind"] == "error"
    assert "error" == events[-1]["kind"] and events[-1]["message"]


def test_proxy_mode_writes_custom_provider_and_routes_inner_model(
    fake_mimo_bin, tmp_path
):
    """In proxy mode (OPENAI_BASE_URL set), start() must register a custom
    OpenAI-compatible ``benchflow`` provider at the proxy and route the turn as
    ``benchflow/<safe_alias>`` so MiMo POSTs to benchflow's usage proxy (which is
    what lets benchflow write trajectory/llm_trajectory.jsonl). The bare
    ``benchflow-*`` alias is models.dev-invalid and MiMo would reject it
    directly -- only a custom-provider id is accepted."""

    captured = {}

    async def go():
        env = dict(os.environ)
        env["OPENAI_BASE_URL"] = "http://127.0.0.1:65500/v1"
        env["OPENAI_API_KEY"] = "sk-proxy"
        client = await MimoAcp.start(
            mimo_bin=fake_mimo_bin,
            cwd=str(tmp_path),
            model="benchflow-deepseek-deepseek-v4-flash",
            env=env,
        )
        captured["inner_model"] = client.inner_model
        await client.close()

    asyncio.run(asyncio.wait_for(go(), timeout=20))

    cfg_path = tmp_path / ".mimocode" / "mimocode.json"
    assert cfg_path.exists(), "proxy mode must write .mimocode/mimocode.json"
    cfg = _json.loads(cfg_path.read_text())
    prov = cfg["provider"]["benchflow"]
    assert prov["npm"] == "@ai-sdk/openai-compatible"
    assert prov["options"]["baseURL"] == "http://127.0.0.1:65500/v1"
    assert prov["options"]["apiKey"] == "sk-proxy"
    # the models-map key is exactly safe_model_alias (already-aliased: unchanged)
    alias = "benchflow-deepseek-deepseek-v4-flash"
    assert safe_model_alias("benchflow-deepseek-deepseek-v4-flash") == alias
    assert alias in prov["models"]
    assert prov["models"][alias] == {"name": alias}
    # the turn is routed as benchflow/<alias> (a custom-provider id MiMo accepts)
    assert captured["inner_model"] == "benchflow/" + alias


def test_proxy_alias_sanitised_to_safe_model_alias(fake_mimo_bin, tmp_path):
    """A provider/model id (slashes, dots) is sanitised to the same
    ``benchflow-<...>`` shape benchflow's safe_model_alias produces, so the
    custom-provider models-map key matches what the proxy actually serves."""

    captured = {}

    async def go():
        env = dict(os.environ)
        env["OPENAI_BASE_URL"] = "http://127.0.0.1:65500/v1"
        client = await MimoAcp.start(
            mimo_bin=fake_mimo_bin,
            cwd=str(tmp_path),
            model="deepseek/deepseek-v4-flash",
            env=env,
        )
        captured["inner_model"] = client.inner_model
        await client.close()

    asyncio.run(asyncio.wait_for(go(), timeout=20))
    cfg = _json.loads((tmp_path / ".mimocode" / "mimocode.json").read_text())
    key = next(iter(cfg["provider"]["benchflow"]["models"]))
    assert key.startswith("benchflow-")
    assert "/" not in key
    # the models-map key is EXACTLY benchflow's safe_model_alias for the id —
    # not the old inline regex (which dropped the sha1/empty-string cases)
    expected = safe_model_alias("deepseek/deepseek-v4-flash")
    assert key == expected == "benchflow-deepseek-deepseek-v4-flash"
    assert captured["inner_model"] == "benchflow/" + expected


def test_safe_model_alias_matches_benchflow_incl_edge_cases():
    """The module's safe_model_alias must reproduce benchflow's exactly,
    including the >96-char sha1 truncation and the empty-string fallback the
    old inline regex omitted (both can 404 the inner model at the proxy)."""
    # already-aliased: returned unchanged
    assert safe_model_alias("benchflow-foo") == "benchflow-foo"
    # provider/model id: slashes/dots collapse to a benchflow-<...> id
    assert safe_model_alias("deepseek/deepseek-v4-flash") == (
        "benchflow-deepseek-deepseek-v4-flash"
    )
    # empty / all-special id falls back to "model" (never a bare "benchflow-")
    assert safe_model_alias("///") == "benchflow-model"
    assert safe_model_alias("") == "benchflow-model"
    # >96 chars: sha1-suffixed and length-bounded (never the raw long string)
    long_model = "x" * 200
    alias = safe_model_alias(long_model)
    assert alias.startswith("benchflow-")
    assert len(alias) < len("benchflow-" + long_model)
    # deterministic
    assert safe_model_alias(long_model) == alias
    # if benchflow is importable, the module alias must equal it bit-for-bit
    try:
        from benchflow.providers.litellm_config import (
            safe_model_alias as bf_alias,
        )
    except Exception:  # pragma: no cover - benchflow not installed in this env
        bf_alias = None
    if bf_alias is not None:
        for m in ("deepseek/deepseek-v4-flash", "x" * 200, "a.b/c:d", "model"):
            assert safe_model_alias(m) == bf_alias(m), m


def test_native_mode_writes_no_proxy_config(fake_mimo_bin, tmp_path):
    """Free mimo/mimo-auto path (no OPENAI_BASE_URL) must NOT write a proxy
    provider -- usage_tracking=off stays native (un-proxied), unchanged."""

    async def go():
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_BASE_URL"}
        await (
            await MimoAcp.start(
                mimo_bin=fake_mimo_bin,
                cwd=str(tmp_path),
                model="mimo/mimo-auto",
                env=env,
            )
        ).close()

    asyncio.run(asyncio.wait_for(go(), timeout=20))
    assert not (tmp_path / ".mimocode" / "mimocode.json").exists()


if sys.platform == "win32":  # pragma: no cover - asyncio subprocess needs a real shell
    pytest.skip("ACP subprocess tests require POSIX", allow_module_level=True)

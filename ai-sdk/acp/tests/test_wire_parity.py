"""Offline, load-bearing wire-parity re-assertion for ai-sdk/acp.

Runs entirely from recorded fixtures — no live model, no node, no benchflow:

  fixtures/vanilla-outside.jsonl  — STANDALONE native capture (server.mjs driven
                                    by acp_capture.mjs against the mock upstream).
  fixtures/vanilla-inside.jsonl   — BENCHFLOW-HOSTED capture (docker sandbox +
                                    LiteLLM gateway forwarding to the SAME mock).

Both recorded on the fixed parity task ("Create a file named hello.txt in the
current directory containing exactly: Hello, world!") with model deepseek-v4-flash.

HONEST RESULT (2026-06-27, ai-sdk/acp). The canonical comparator
(`parity.compare_captures` / `assert_wire_parity`) FAILs on exactly one field:
req#1's writeFile tool-RESULT absolute path. The cause is a sandbox-cwd CAPTURE
asymmetry, not agent or gateway behavior — the standalone capture ran in a host
temp dir (/tmp/parity-XXXX) while the hosted run ran in the sandbox root (/app).
The `sandbox-cwd` NEUTRAL_DIFF is meant to collapse exactly this, but it cannot
here: the ai-sdk server's cwd-INDEPENDENT system prompt keeps the cwd out of
every model-visible string, so `parity._cwd_from_messages` cannot recover the
standalone temp cwd and only the hard-coded `/app` token (hosted side) collapses.

Everything the model conditions on — system prompt, user message, tools + JSON
schemas, tool_choice, sampling params (stream/stream_options), model, the
assistant tool_call + tool_call_id — is byte-identical, proven below by collapsing
the standalone cwd symmetrically.

This is a CHARACTERIZATION test: it pins the recorded divergence, proves it is
isolated + neutral-by-intent, and is load-bearing (any drift in the
model-conditioning bytes flips the green assertions red). When the capture tooling
is fixed — capture the standalone fixture in /app, OR feed acp_capture's already
known cwd into the `sandbox-cwd` rule — `test_canonical_wire_parity_known_divergence`
will XPASS (strict) and force its own promotion to a plain PASS.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
# Import the CANONICAL parity module (no vendored copy -> the documented allowlist
# in parity.NEUTRAL_DIFFS cannot silently drift from this test).
_SCRIPTS = (
    Path(__file__).resolve().parents[3] / "skills" / "adaptation-parity" / "scripts"
)
sys.path.insert(0, str(_SCRIPTS))

from parity import (  # noqa: E402
    assert_wire_parity,
    compare_captures,
    load_capture,
    normalize_request,
)

OUTSIDE = FIXTURES / "vanilla-outside.jsonl"
INSIDE = FIXTURES / "vanilla-inside.jsonl"


def test_captures_have_two_real_upstream_requests() -> None:
    out, ins = load_capture(str(OUTSIDE)), load_capture(str(INSIDE))
    assert len(out) == len(ins) == 2
    for reqs in (out, ins):
        assert len(reqs[0]["messages"]) == 2  # system + user
        assert len(reqs[1]["messages"]) == 4  # + assistant tool_call + tool result
        assert [t["function"]["name"] for t in reqs[0]["tools"]] == [
            "bash",
            "writeFile",
            "readFile",
        ]


def test_request0_is_byte_identical_modulo_allowlist() -> None:
    out, ins = load_capture(str(OUTSIDE)), load_capture(str(INSIDE))
    assert normalize_request(out[0]) == normalize_request(ins[0])


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN sandbox-cwd CAPTURE asymmetry: standalone ran in /tmp/parity-XXXX, "
    "hosted in /app; the cwd-hardened server keeps the cwd out of model-visible text, "
    "so the sandbox-cwd rule only collapses the hosted /app. Fix the capture tooling "
    "(capture standalone in /app, or feed acp_capture's cwd into the rule) and delete "
    "this marker.",
)
def test_canonical_wire_parity_known_divergence() -> None:
    assert_wire_parity(load_capture(str(OUTSIDE)), load_capture(str(INSIDE)))


def test_divergence_is_isolated_to_req1_toolresult_cwd() -> None:
    """Pin the failure: req#1 `messages` only, and exactly the writeFile
    tool-RESULT absolute path (standalone temp cwd vs hosted /app)."""
    res = compare_captures(load_capture(str(OUTSIDE)), load_capture(str(INSIDE)))
    assert res.ok is False
    failing = [r for r in res.requests if not r.equal]
    assert [r.index for r in failing] == [1]
    assert failing[0].differing_fields == ["messages"]

    no = normalize_request(load_capture(str(OUTSIDE))[1])
    ni = normalize_request(load_capture(str(INSIDE))[1])
    diffs = [
        (a.get("content"), b.get("content"))
        for a, b in zip(no["messages"], ni["messages"])
        if a != b
    ]
    assert len(diffs) == 1
    out_c, in_c = diffs[0]
    assert in_c == "wrote N bytes to <CWD>/hello.txt"  # hosted /app collapsed
    assert re.fullmatch(r"wrote N bytes to /tmp/parity-\w+/hello\.txt", out_c)


def test_model_conditioning_identical_after_symmetric_cwd_collapse() -> None:
    """Proof the SOLE difference is the sandbox cwd: collapse the standalone temp
    cwd the same way the rule collapses the hosted /app, and every upstream request
    is byte-identical — same system prompt, user message, tools, sampling params,
    model, tool_call + tool_call_id."""
    out, ins = load_capture(str(OUTSIDE)), load_capture(str(INSIDE))
    cwd = None
    for m in normalize_request(out[1])["messages"]:
        if m.get("role") == "tool":
            mt = re.search(r"to (\S+)/hello\.txt", m["content"])
            if mt:
                cwd = mt.group(1)
    assert cwd and cwd.startswith("/tmp/parity-")

    def collapse(reqs: list[dict]) -> list[dict]:
        norm = [normalize_request(r) for r in reqs]
        for b in norm:
            for m in b.get("messages", []):
                if isinstance(m.get("content"), str):
                    m["content"] = m["content"].replace(cwd, "<CWD>")
        return norm

    assert collapse(out) == [normalize_request(r) for r in ins]

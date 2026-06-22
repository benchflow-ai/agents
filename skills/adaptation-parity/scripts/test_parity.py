"""Tests for the reusable wire/outcome parity comparator (ADR-0002).

Run: PYTHONPATH=. pytest test_parity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from parity import (  # noqa: E402
    NEUTRAL_DIFFS,
    assert_wire_parity,
    compare_captures,
    compare_outcomes,
    normalize_request,
)

# ── neutral-diff normalization: each rule collapses one expected difference ──


def test_normalize_collapses_gateway_model_alias() -> None:
    """benchflow-<provider>-<model> alias == the same raw upstream model."""
    vanilla = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "hi"}],
    }
    hosted = {
        "model": "benchflow-deepseek-deepseek-v4-flash",
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert normalize_request(vanilla) == normalize_request(hosted)


def test_model_family_divergence_fails() -> None:
    """A genuinely DIFFERENT upstream model must NOT be normalized away (the
    alias rule means 'same upstream model', not 'erase the model')."""
    a = {"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "x"}]}
    b = {"model": "gpt-4o-2024-08-06", "messages": [{"role": "user", "content": "x"}]}
    assert not compare_captures([a], [b]).ok
    # the benchflow alias of a *different* model also differs from the raw model
    c = {
        "model": "benchflow-openai-gpt-4o",
        "messages": [{"role": "user", "content": "x"}],
    }
    assert not compare_captures([a], [c]).ok


def test_neutral_diffs_drive_normalization() -> None:
    """NEUTRAL_DIFFS is load-bearing: excluding a rule disables its normalization."""
    alias = {"model": "benchflow-deepseek-deepseek-v4-flash", "messages": []}
    raw = {"model": "deepseek-v4-flash", "messages": []}
    assert normalize_request(alias) == normalize_request(raw)  # rule active -> equal
    # exclude the rule -> the alias is left verbatim -> they differ
    assert normalize_request(alias, rules=[]) != normalize_request(raw, rules=[])


def test_normalize_collapses_sandbox_cwd() -> None:
    vanilla = {
        "model": "m",
        "messages": [{"role": "system", "content": "cwd is directory /home/u/proj."}],
    }
    hosted = {
        "model": "m",
        "messages": [{"role": "system", "content": "cwd is directory /app."}],
    }
    assert normalize_request(vanilla) == normalize_request(hosted)


def test_app_substring_not_overcollapsed() -> None:
    """/app must only match at a path boundary, not inside /application/..."""
    body = {
        "model": "m",
        "messages": [{"role": "tool", "content": "see /application/data.json"}],
    }
    out = normalize_request(body)
    assert "/application/data.json" in out["messages"][0]["content"]


def test_cwd_replace_is_path_boundary_anchored() -> None:
    """When the request's own cwd is itself a prefix of a longer unrelated path,
    the cwd replace must be path-boundary-anchored — exactly like the /app token.

    Regression: an UNANCHORED ``text.replace(cwd, "<CWD>")`` corrupts a longer
    path that merely starts with the cwd string (cwd="/app" turns the unrelated
    "/application/data" into "<CWD>lication/data"), which the vanilla side (a
    different/absent cwd) keeps verbatim -> a FALSE parity FAIL on equivalent
    agents. The standalone cwd token must still collapse to <CWD>.
    """
    body = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "working directory /app."},
            {"role": "tool", "content": "read /app/data and /application/cfg"},
        ],
    }
    out = normalize_request(body)
    content = out["messages"][1]["content"]
    # the unrelated longer path is preserved, NOT corrupted to "<CWD>lication/cfg"
    assert "/application/cfg" in content
    assert "<CWD>lication/cfg" not in content
    # the real cwd path (boundary-anchored: next char '/') still collapses
    assert "<CWD>/data" in content


def test_normalize_collapses_prompt_trailing_whitespace() -> None:
    a = {"model": "m", "messages": [{"role": "user", "content": "do the task"}]}
    b = {"model": "m", "messages": [{"role": "user", "content": "do the task   \n"}]}
    assert normalize_request(a) == normalize_request(b)


def test_normalize_collapses_assistant_content_null_vs_omitted() -> None:
    a = {
        "model": "m",
        "messages": [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]}
        ],
    }
    b = {"model": "m", "messages": [{"role": "assistant", "tool_calls": [{"id": "1"}]}]}
    assert normalize_request(a) == normalize_request(b)


def test_wrote_n_bytes_normalized_only_in_tool_results() -> None:
    """The byte count is neutral in a tool RESULT (sampling-dependent), but NOT
    in assistant prose / tool-call arguments — scoping prevents masking there."""
    tool_a = {"model": "m", "messages": [{"role": "tool", "content": "wrote 5 bytes"}]}
    tool_b = {
        "model": "m",
        "messages": [{"role": "tool", "content": "wrote 9999 bytes"}],
    }
    assert normalize_request(tool_a) == normalize_request(tool_b)
    prose_a = {
        "model": "m",
        "messages": [{"role": "assistant", "content": "I wrote 5 bytes"}],
    }
    prose_b = {
        "model": "m",
        "messages": [{"role": "assistant", "content": "I wrote 9999 bytes"}],
    }
    assert normalize_request(prose_a) != normalize_request(prose_b)


def test_write_directory_divergence_fails() -> None:
    """Same filename, different write DIRECTORY (under each side's cwd) is real."""
    a = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "directory /home/u/proj"},
            {"role": "tool", "content": "wrote 12 bytes to /home/u/proj/src/index.ts"},
        ],
    }
    b = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "directory /app"},
            {"role": "tool", "content": "wrote 88 bytes to /app/tests/index.ts"},
        ],
    }
    assert not compare_captures([a], [b]).ok  # src/ vs tests/ must surface


def test_same_relative_write_path_is_neutral() -> None:
    """Same relative path under each side's own cwd is neutral (sandbox-cwd)."""
    a = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "directory /home/u/proj"},
            {"role": "tool", "content": "wrote 12 bytes to /home/u/proj/out.txt"},
        ],
    }
    b = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "directory /app"},
            {"role": "tool", "content": "wrote 88 bytes to /app/out.txt"},
        ],
    }
    assert compare_captures([a], [b]).ok


def test_neutral_diff_allowlist_is_explicit() -> None:
    """The allowlist is reviewable data, not buried in code (ADR-0002)."""
    for rule in (
        "gateway-model-alias",
        "sandbox-cwd",
        "prompt-trailing-whitespace",
        "assistant-content-null-vs-omitted",
        "wrote-N-bytes",
    ):
        assert rule in NEUTRAL_DIFFS


# ── wire-parity comparison: real divergences must FAIL ──


def test_compare_captures_passes_on_neutral_only_diffs() -> None:
    expected = [
        {"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "hi"}]}
    ]
    actual = [
        {
            "model": "benchflow-deepseek-deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hi\n"}],
        }
    ]
    assert compare_captures(expected, actual).ok


def test_compare_captures_detects_real_divergence() -> None:
    expected = [{"model": "m", "temperature": 0.0, "messages": []}]
    actual = [{"model": "m", "temperature": 0.7, "messages": []}]
    res = compare_captures(expected, actual)
    assert not res.ok
    assert "temperature" in res.requests[0].differing_fields


def test_compare_captures_detects_count_mismatch() -> None:
    res = compare_captures([{"model": "m"}], [{"model": "m"}, {"model": "m"}])
    assert not res.ok
    assert res.n_expected == 1 and res.n_actual == 2


def test_assert_wire_parity_raises_on_divergence_passes_on_parity() -> None:
    ok_e = [
        {"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "x"}]}
    ]
    ok_a = [
        {
            "model": "benchflow-deepseek-deepseek-v4-flash",
            "messages": [{"role": "user", "content": "x\n"}],
        }
    ]
    assert_wire_parity(ok_e, ok_a)  # must not raise
    with pytest.raises(AssertionError):
        assert_wire_parity(
            [{"model": "m", "temperature": 0.0}], [{"model": "m", "temperature": 1.0}]
        )


# ── outcome parity: reward + tool sequence; token counts ignored ──


def test_compare_outcomes_ignores_token_counts() -> None:
    expected = {"reward": 1.0, "tools": ["read", "write"], "tokens": 100}
    actual = {"reward": 1.0, "tools": ["read", "write"], "tokens": 250}
    assert compare_outcomes(expected, actual).ok


def test_compare_outcomes_flags_reward_and_tool_divergence() -> None:
    expected = {"reward": 1.0, "tools": ["read", "write"]}
    assert not compare_outcomes(
        expected, {"reward": 0.0, "tools": ["read", "write"]}
    ).ok
    assert not compare_outcomes(expected, {"reward": 1.0, "tools": ["read"]}).ok

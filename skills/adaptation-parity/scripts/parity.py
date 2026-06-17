#!/usr/bin/env python3
"""Reusable wire/outcome parity comparator (ADR-0002).

Generalizes the original ``parity_diff.py`` script into an importable,
allowlist-driven module a per-agent test can call against a recorded
standalone-vanilla fixture:

  from parity import assert_wire_parity, compare_outcomes, load_capture
  assert_wire_parity(load_capture("fixtures/vanilla.jsonl"),
                     load_capture("captured/hosted.jsonl"))

"Vanilla" is the agent run standalone on its native platform; the hosted capture
is the agent run through BenchFlow's gateway. Wire parity holds when, after
collapsing the explicit ``NEUTRAL_DIFFS``, every upstream request is byte-identical.

The neutral-diff rules are a load-bearing registry (``_RULES``): ``NEUTRAL_DIFFS``
is derived from it and ``normalize_request(body, rules=...)`` applies exactly the
named subset, so the documented allowlist cannot silently drift from behavior.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

_BENCHFLOW_ALIAS_PREFIX = "benchflow-"


def _canonical_model(model: object) -> object:
    """Reduce a model id to its provider-agnostic upstream name so the gateway's
    ``benchflow-<provider>-<model>`` alias compares equal to the raw model — while
    a genuinely different model (family) still differs. We strip ONLY the documented
    alias prefix + provider segment, never the model itself."""
    if not isinstance(model, str):
        return model
    m = model
    if m.startswith(_BENCHFLOW_ALIAS_PREFIX):
        # benchflow-<provider>-<safe_model> -> drop "benchflow-" + the provider seg
        _, _, rest = m[len(_BENCHFLOW_ALIAS_PREFIX) :].partition("-")
        m = rest or m[len(_BENCHFLOW_ALIAS_PREFIX) :]
    if "/" in m:
        m = m.rsplit("/", 1)[-1]  # provider/model raw form -> model
    return m


def _cwd_from_messages(messages: list[dict]) -> str | None:
    for m in messages:
        c = m.get("content")
        if m.get("role") == "system" and isinstance(c, str):
            mt = re.search(r"directory (\S+)", c)
            if mt:
                return mt.group(1).rstrip(".")
    return None


def _sub_cwd(text: str, cwd: str | None) -> str:
    if cwd:
        # `cwd` is the request's own absolute task dir — a long, unique multi-segment
        # path that also appears in prose followed by '.', a space, or EOL — so an
        # unanchored replace is correct here and not collision-prone for real cwds.
        text = text.replace(cwd, "<CWD>")
    # `/app` is a fixed sandbox-root TOKEN, so it IS boundary-anchored (next char /,
    # quote, or end) — never collapse it inside an unrelated token like /application.
    return re.sub(r"/app(?=[/\"']|$)", "<CWD>", text)


def _walk_content_strings(body: dict, fn: Callable[[str], str]) -> None:
    """Apply ``fn`` to every model-visible string: message content + tool-call
    argument strings."""
    for m in body.get("messages", []):
        if isinstance(m.get("content"), str):
            m["content"] = fn(m["content"])
        for tc in m.get("tool_calls") or []:
            args = (tc.get("function") or {}).get("arguments")
            if isinstance(args, str):
                tc["function"]["arguments"] = fn(args)


# ── neutral-diff rules. The registry IS the allowlist (load-bearing). ──


def _rule_model_alias(body: dict) -> None:
    body["model"] = _canonical_model(body.get("model"))


def _rule_sandbox_cwd(body: dict) -> None:
    cwd = _cwd_from_messages(body.get("messages", []))
    _walk_content_strings(body, lambda t: _sub_cwd(t, cwd))


def _rule_prompt_trailing_ws(body: dict) -> None:
    for m in body.get("messages", []):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            m["content"] = m["content"].rstrip()


def _rule_assistant_content_null(body: dict) -> None:
    for m in body.get("messages", []):
        if m.get("role") == "assistant" and m.get("content") is None:
            m.pop("content", None)


def _rule_wrote_n_bytes(body: dict) -> None:
    # The byte count varies with sampling. Scope to tool-RESULT content ONLY, so
    # it cannot mask a divergence in assistant prose or tool-call arguments. The
    # write *directory* is left to the sandbox-cwd rule (cwd prefix -> <CWD>), so a
    # genuinely different write dir (same filename) still differs.
    for m in body.get("messages", []):
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            m["content"] = re.sub(r"wrote \d+ bytes", "wrote N bytes", m["content"])


_RULES: list[tuple[str, Callable[[dict], None]]] = [
    (
        "gateway-model-alias",
        _rule_model_alias,
    ),  # benchflow-<provider>- alias -> same model
    ("sandbox-cwd", _rule_sandbox_cwd),  # task cwd / sandbox /app -> <CWD>
    (
        "prompt-trailing-whitespace",
        _rule_prompt_trailing_ws,
    ),  # BenchFlow .strip()s the prompt
    (
        "assistant-content-null-vs-omitted",
        _rule_assistant_content_null,
    ),  # LiteLLM re-aggregation
    ("wrote-N-bytes", _rule_wrote_n_bytes),  # byte count in a write tool-result
]

#: The explicit, reviewable allowlist of expected-neutral differences. Anything
#: NOT collapsed by a rule here (a changed sampling param, a reshaped tool schema,
#: a dropped field the model conditions on, a different model) is a real divergence.
NEUTRAL_DIFFS: list[str] = [name for name, _ in _RULES]


def normalize_request(body: dict, rules: Iterable[str] | None = None) -> dict:
    """Collapse the expected-neutral differences (a subset of ``NEUTRAL_DIFFS``,
    default all) so two captures of the *same* behavior compare equal."""
    active = set(NEUTRAL_DIFFS if rules is None else rules)
    b = json.loads(json.dumps(body))
    for name, fn in _RULES:
        if name in active:
            fn(b)
    return b


@dataclass
class RequestComparison:
    index: int
    equal: bool
    differing_fields: list[str] = field(default_factory=list)


@dataclass
class WireParityResult:
    ok: bool
    n_expected: int
    n_actual: int
    requests: list[RequestComparison] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"wire-parity: {'PASS' if self.ok else 'FAIL'} "
            f"(expected={self.n_expected} actual={self.n_actual})"
        ]
        if self.n_expected != self.n_actual:
            lines.append(
                f"  request COUNT mismatch: {self.n_expected} vs {self.n_actual}"
            )
        for r in self.requests:
            if not r.equal:
                lines.append(f"  req#{r.index}: differing fields {r.differing_fields}")
        return "\n".join(lines)


def compare_captures(expected: list[dict], actual: list[dict]) -> WireParityResult:
    """Compare two upstream-request captures after neutral normalization."""
    n_e, n_a = len(expected), len(actual)
    ok = n_e == n_a
    reqs: list[RequestComparison] = []
    for i in range(min(n_e, n_a)):
        ne, na = normalize_request(expected[i]), normalize_request(actual[i])
        if ne == na:
            reqs.append(RequestComparison(i, True))
        else:
            diff = sorted(k for k in set(ne) | set(na) if ne.get(k) != na.get(k))
            reqs.append(RequestComparison(i, False, diff))
            ok = False
    return WireParityResult(ok, n_e, n_a, reqs)


def assert_wire_parity(expected: list[dict], actual: list[dict]) -> None:
    """pytest-friendly: raise AssertionError with a readable summary on divergence."""
    res = compare_captures(expected, actual)
    if not res.ok:
        raise AssertionError(res.summary())


@dataclass
class OutcomeParityResult:
    ok: bool
    reward_equal: bool
    tools_equal: bool
    detail: str = ""


def compare_outcomes(expected: dict, actual: dict) -> OutcomeParityResult:
    """Outcome parity = same reward + same tool sequence. Token counts vary within
    sampling non-determinism and are explicitly NOT compared."""
    reward_equal = expected.get("reward") == actual.get("reward")
    tools_equal = list(expected.get("tools", [])) == list(actual.get("tools", []))
    parts = []
    if not reward_equal:
        parts.append(f"reward {expected.get('reward')!r} != {actual.get('reward')!r}")
    if not tools_equal:
        parts.append(
            f"tool sequence {expected.get('tools')!r} != {actual.get('tools')!r}"
        )
    return OutcomeParityResult(
        reward_equal and tools_equal, reward_equal, tools_equal, "; ".join(parts)
    )


def load_capture(path: str) -> list[dict]:
    """Load upstream request bodies from a mock_upstream.mjs JSONL capture."""
    with open(path) as fh:
        return [json.loads(line)["body"] for line in fh if line.strip()]

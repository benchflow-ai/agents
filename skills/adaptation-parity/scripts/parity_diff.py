#!/usr/bin/env python3
"""Diff two upstream-request captures (from mock_upstream.mjs) for behavioral
parity, normalizing the expected-neutral gateway/env differences.

  python parity_diff.py <outside.jsonl> <inside.jsonl>

PASS  = after normalization, every upstream request is byte-identical (same
        messages, tools, and sampling params — what the model conditions on).
Neutral diffs normalized away: gateway model-alias rename; sandbox cwd vs local
in the system prompt; trailing whitespace on the prompt; the `content: null` vs
omitted on a tool-call assistant turn (LiteLLM stream re-aggregation); the byte
count in a "wrote N bytes" tool result.
"""
import json
import re
import sys


def load(path):
    return [json.loads(line)["body"] for line in open(path) if line.strip()]


def normalize(body):
    b = json.loads(json.dumps(body))
    b["model"] = "<MODEL>"  # gateway alias rename — neutral (same upstream model)
    cwd = None
    for m in b.get("messages", []):
        c = m.get("content")
        if m.get("role") == "system" and isinstance(c, str):
            mt = re.search(r"directory (\S+)", c)
            if mt:
                cwd = mt.group(1).rstrip(".")
        if m.get("role") == "user" and isinstance(c, str):
            m["content"] = c.rstrip()  # prompt trailing whitespace (.strip()) — neutral
        if m.get("role") == "assistant" and m.get("content") is None:
            m.pop("content", None)  # null vs omitted — neutral
    s = json.dumps(b)
    if cwd:
        s = s.replace(cwd, "<CWD>")
    s = s.replace("/app", "<CWD>")
    s = re.sub(r"wrote \d+ bytes", "wrote N bytes", s)
    # tool-result file paths differ only by working dir (sandbox /app vs local
    # tmp) — collapse the absolute dir to <CWD> so the deliverable is compared,
    # not where it landed.
    s = re.sub(r"(wrote N bytes to )\S+/", r"\1<CWD>/", s)
    return json.loads(s)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    a, b = load(sys.argv[1]), load(sys.argv[2])
    print(f"requests: {sys.argv[1]}={len(a)}  {sys.argv[2]}={len(b)}")
    ok = len(a) == len(b)
    for i in range(min(len(a), len(b))):
        na, nb = normalize(a[i]), normalize(b[i])
        eq = na == nb
        ok &= eq
        print(f"  req#{i}: EQUAL={eq}")
        if not eq:
            for k in sorted(set(na) | set(nb)):
                if na.get(k) != nb.get(k):
                    print(f"    field [{k}] differs")
    print("\nPARITY:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

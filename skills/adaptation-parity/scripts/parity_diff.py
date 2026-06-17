#!/usr/bin/env python3
"""Diff two upstream-request captures (from mock_upstream.mjs) for behavioral
parity — a thin CLI over :mod:`parity`.

  python parity_diff.py <outside.jsonl> <inside.jsonl>

PASS (exit 0) = after normalizing the expected-neutral gateway/env differences
(see ``parity.NEUTRAL_DIFFS``), every upstream request is byte-identical — same
messages, tools, and sampling params (what the model conditions on). Any other
difference is a real divergence and FAILs (exit 1).
"""

import sys

from parity import compare_captures, load_capture


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    expected, actual = load_capture(sys.argv[1]), load_capture(sys.argv[2])
    res = compare_captures(expected, actual)
    print(f"captures: {sys.argv[1]}={res.n_expected}  {sys.argv[2]}={res.n_actual}")
    print(res.summary())
    print("\nPARITY:", "PASS" if res.ok else "FAIL")
    sys.exit(0 if res.ok else 1)


if __name__ == "__main__":
    main()

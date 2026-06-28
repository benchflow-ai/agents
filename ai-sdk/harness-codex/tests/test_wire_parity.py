"""Uniform ai-sdk wire-parity test (ADR-0002).

The test logic lives ONCE in
``skills/adaptation-parity/scripts/path_wire_parity.py``; this package contributes
only its recorded fixture data (``tests/fixtures/vanilla.jsonl`` + ``summary.json``).
This shim is byte-identical across every ``ai-sdk/<agent>/`` package.
"""

import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0, str(_PKG_ROOT.parents[1] / "skills" / "adaptation-parity" / "scripts")
)

from path_wire_parity import make_parity_tests  # noqa: E402

(
    test_offline_redrive_matches_vanilla_fixture,
    test_vanilla_fixture_is_loadable_and_self_consistent,
) = make_parity_tests(_PKG_ROOT)

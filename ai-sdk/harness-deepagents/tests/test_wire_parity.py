"""Uniform ai-sdk wire-parity test (ADR-0002) — scaffolded, fixture pending.

The test logic lives ONCE in
``skills/adaptation-parity/scripts/path_wire_parity.py``; a package activates it by
committing its recorded fixture (``tests/fixtures/vanilla.jsonl`` + ``summary.json``).
harness-deepagents has no recorded fixture yet, so both parity tests SKIP (next step)
instead of failing; once a fixture lands they delegate to the shared mechanism, which
is byte-identical across every ``ai-sdk/<agent>/`` package.
"""

import sys
from pathlib import Path

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0, str(_PKG_ROOT.parents[1] / "skills" / "adaptation-parity" / "scripts")
)

from path_wire_parity import make_parity_tests  # noqa: E402

_FIXTURE = _PKG_ROOT / "tests" / "fixtures" / "vanilla.jsonl"

if _FIXTURE.exists():
    (
        test_offline_redrive_matches_vanilla_fixture,
        test_vanilla_fixture_is_loadable_and_self_consistent,
    ) = make_parity_tests(_PKG_ROOT)
else:

    @pytest.mark.skip(reason="no vanilla fixture yet (next step)")
    def test_offline_redrive_matches_vanilla_fixture() -> None: ...

    @pytest.mark.skip(reason="no vanilla fixture yet (next step)")
    def test_vanilla_fixture_is_loadable_and_self_consistent() -> None: ...

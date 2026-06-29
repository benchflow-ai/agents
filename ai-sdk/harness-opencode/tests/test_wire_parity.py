"""Uniform ai-sdk wire-parity test (ADR-0002).

The test logic lives ONCE in
``skills/adaptation-parity/scripts/path_wire_parity.py``; each package contributes
only its recorded fixture data (``tests/fixtures/vanilla.jsonl`` + ``summary.json``).

SKIPPED: this package has no recorded ``vanilla.jsonl`` yet — wire-parity is part
of the next step (model routing + parity verification), so the shim is disabled
rather than left failing.
"""

import pytest

pytestmark = pytest.mark.skip(reason="no vanilla fixture yet (next step)")

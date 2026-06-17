"""Regression for the CI path-filter typo (greptile P2).

`.github/workflows/test-ai-sdk-harness-mimo.yaml` filtered on
`.github/workflows/test-ai-sdk/harness-mimo.yaml` (a slash instead of a hyphen).
That path never matches the real file, so edits to the workflow itself would not
re-trigger it. Validate that every workflow-path filter resolves to a real file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _repo_root() -> Path | None:
    for anc in Path(__file__).resolve().parents:
        if (anc / ".github" / "workflows").is_dir():
            return anc
    return None


def test_workflow_path_filters_reference_existing_files() -> None:
    root = _repo_root()
    if root is None:
        pytest.skip("repo .github/workflows not present (standalone install)")
    wf = root / ".github" / "workflows" / "test-ai-sdk-harness-mimo.yaml"
    assert wf.exists(), "this package's workflow file is missing"
    text = wf.read_text()
    refs = sorted(set(re.findall(r"\.github/workflows/[\w./-]+\.ya?ml", text)))
    assert refs, "expected at least one .github/workflows/* path filter to validate"
    missing = [r for r in refs if not (root / r).exists()]
    assert not missing, (
        f"path filter(s) reference non-existent workflow file(s): {missing}"
    )

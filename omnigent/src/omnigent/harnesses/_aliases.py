"""Harness-name aliases — a faithful mirror of omnigent's ``harness_aliases.py``.

Vendored (not imported) from omnigent **v0.3.0**
(``omnigent/harness_aliases.py``): the upstream ``omnigent`` package installs
only inside the sandbox and its top-level package name collides with THIS
adapter package (both are ``omnigent``), so we cannot import it host-side at
registration time. Keep this in sync when bumping ``register.OMNIGENT_PIN`` — the
alias/native sets are asserted against this mirror in ``tests/test_harnesses.py``.

Purpose here: validate that our per-harness ``slug``/``harness_value`` set is the
canonical omnigent set (aliases folded) and that every ``native=True`` spec is a
real omnigent native harness.
"""

from __future__ import annotations

# alias -> canonical omnigent ``--harness`` value (mirror of upstream HARNESS_ALIASES).
HARNESS_ALIASES: dict[str, str] = {
    "claude": "claude-sdk",
    "native-kiro": "kiro-native",
    "native-pi": "pi-native",
    "openai-agents-sdk": "openai-agents",
    "agy": "antigravity",
    "google-antigravity": "antigravity",
    "kimi-code": "kimi",
    "native-goose": "goose-native",
    "native-kimi": "kimi-native",
    "qwen-code": "qwen",
    "native-qwen": "qwen-native",
    "opencode": "opencode-native",
    "native-opencode": "opencode-native",
    "native-hermes": "hermes-native",
    "github-copilot": "copilot",
}

# Canonical + reversed native-CLI harness spellings (mirror of upstream
# NATIVE_HARNESSES).
NATIVE_HARNESSES: frozenset[str] = frozenset(
    {
        "claude-native",
        "native-claude",
        "codex-native",
        "native-codex",
        "pi-native",
        "native-pi",
        "cursor-native",
        "native-cursor",
        "kiro-native",
        "native-kiro",
        "antigravity-native",
        "native-antigravity",
        "goose-native",
        "native-goose",
        "qwen-native",
        "native-qwen",
        "opencode-native",
        "native-opencode",
        "kimi-native",
        "native-kimi",
        "hermes-native",
        "native-hermes",
    }
)


def canonicalize_harness(harness: str | None) -> str | None:
    """Return the canonical harness id for *harness* (unknown names unchanged)."""
    if harness is None:
        return None
    return HARNESS_ALIASES.get(harness, harness)


def is_native_harness(harness: str | None) -> bool:
    """Return whether *harness* is one of omnigent's native-CLI harnesses."""
    if harness is None:
        return False
    return (canonicalize_harness(harness) or harness) in NATIVE_HARNESSES

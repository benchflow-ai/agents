"""Freshness tests: base64-embedded launchers must track their source of truth.

Two drift hazards, one per section below:

1. pi-acp — its launcher's source of truth lives in benchflow *core*
   (``pi_acp_launcher.py``), so the embed can only be pinned semantically.
   agents#17 hand-embedded the *pre-#831* launcher into
   ``acp/pi-acp/manifest.toml``. That launcher hardcoded
   ``_DEFAULT_MAX_TOKENS = 16384`` — the #829 bug: some OpenAI-compatible
   providers reject a 16k ``max_tokens`` and the agent falls into a retry
   storm. benchflow#831 hardened core to cap the fallback completion budget at
   4096 (1/4 of the context window, whichever is smaller) via
   ``_default_max_tokens()`` / ``_positive_int()``. The decoupled path
   (``BENCHFLOW_AGENTS_DIR``) runs the *manifest's* embedded launcher, not
   core — so a stale manifest silently reintroduces #829. These tests extract
   the embedded launcher and pin its token behaviour to post-#831 core.

2. Sibling-source launchers (prime-agent, agents#62, and any future agent
   using the pattern) — the plaintext launcher is committed next to the
   manifest (``acp/<name>/launcher.sh``) and embedded as base64 in
   ``install_cmd``. The embed is what actually runs in the sandbox; the
   sibling file is what humans review and edit. A byte-compare pins them
   together: editing one without regenerating the other fails here.

3. OpenClaw — its Python shim is committed beside its manifest while the
   manifest carries the deployed bytes inline. The explicit target mapping
   below keeps those bytes equal without assuming every sibling Python file is
   a launcher payload.

Run: PYTHONPATH=. pytest test_manifest_launcher_freshness.py
"""

from __future__ import annotations

import base64
import re
import tomllib
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = _REPO_ROOT / "acp" / "pi-acp" / "manifest.toml"

# install_cmd hand-embeds the launcher as:
#   echo <BLOB> | base64 -d > /opt/benchflow/bin/pi-acp-launcher
_BLOB_RE = re.compile(
    r"echo\s+([A-Za-z0-9+/=]+)\s*\|\s*base64\s+-d\s*>\s*"
    r"/opt/benchflow/bin/pi-acp-launcher"
)


def _embedded_launcher_source() -> str:
    text = _MANIFEST.read_text()
    m = _BLOB_RE.search(text)
    assert m, f"{_MANIFEST}: no base64 pi-acp-launcher blob in install_cmd"
    return base64.b64decode(m.group(1)).decode()


def _load_embedded_launcher() -> types.ModuleType:
    """exec the embedded launcher as a module.

    Its ``if __name__ == "__main__"`` guard keeps ``main()`` inert, so loading
    it only defines the module-level constants and helper functions we pin.
    """
    src = _embedded_launcher_source()
    mod = types.ModuleType("pi_acp_launcher_embedded")
    code = compile(src, f"{_MANIFEST}:pi-acp-launcher", "exec")
    exec(code, mod.__dict__)
    return mod


def test_embedded_launcher_does_not_reintroduce_16384_maxtokens() -> None:
    # The #829 bug was a hardcoded 16384 fallback; post-#831 core dropped it.
    src = _embedded_launcher_source()
    assert "_DEFAULT_MAX_TOKENS = 16384" not in src, (
        "pi-acp manifest embeds the pre-#831 launcher (#829: maxTokens=16384). "
        "Re-derive it from benchflow main's pi_acp_launcher.py."
    )
    assert "16384" not in src, "no 16k max_tokens constant may survive anywhere"


def test_embedded_launcher_has_post_831_token_helpers() -> None:
    mod = _load_embedded_launcher()
    # Helpers #831 introduced for context-aware, robust capping.
    assert hasattr(mod, "_positive_int"), "missing _positive_int() (#831)"
    assert hasattr(mod, "_default_max_tokens"), "missing _default_max_tokens() (#831)"
    assert getattr(mod, "_DEFAULT_MAX_TOKENS_CAP", None) == 4096


def test_embedded_launcher_caps_max_tokens_at_4096() -> None:
    mod = _load_embedded_launcher()
    # Large window -> capped at 4096, never window // 4.
    assert mod._default_max_tokens(128000) == 4096
    assert mod._default_max_tokens(1_000_000) == 4096
    # Small window -> 1/4 of it, leaving prompt budget.
    assert mod._default_max_tokens(8000) == 2000
    # Junk / None window -> falls back to the default window, still capped.
    assert mod._default_max_tokens(None) == 4096
    assert mod._default_max_tokens("not-an-int") == 4096
    assert mod._default_max_tokens(0) == 4096
    assert mod._default_max_tokens(-5) == 4096
    # Never zero / negative.
    assert mod._default_max_tokens(1) == 1


def test_embedded_positive_int_matches_core_contract() -> None:
    mod = _load_embedded_launcher()
    assert mod._positive_int(10) == 10
    assert mod._positive_int("10") == 10
    assert mod._positive_int(10.0) == 10
    assert mod._positive_int(0) is None
    assert mod._positive_int(-3) is None
    assert mod._positive_int(10.5) is None
    assert mod._positive_int(True) is None  # bool is not an int budget
    assert mod._positive_int("nope") is None


# ── sibling-source launchers: embed must equal the committed file, byte for byte ──

_LAUNCHER_SOURCES = sorted(_REPO_ROOT.glob("acp/*/launcher.sh"))

# any `echo <BLOB> | base64 -d` (or --decode) stanza inside install_cmd
_ANY_BLOB_RE = re.compile(
    r"\becho\s+([A-Za-z0-9+/=]+)\s*\|\s*base64\s+(?:-d|--decode)\b"
)


@pytest.mark.parametrize("launcher", _LAUNCHER_SOURCES, ids=lambda p: p.parent.name)
def test_embedded_blob_matches_sibling_launcher_source(launcher: Path) -> None:
    manifest = launcher.parent / "manifest.toml"
    assert manifest.is_file(), f"{launcher}: sibling manifest.toml missing"
    install_cmd = tomllib.loads(manifest.read_text())["install_cmd"]
    blobs = _ANY_BLOB_RE.findall(install_cmd)
    assert blobs, (
        f"{manifest}: install_cmd embeds no base64 launcher blob, but "
        f"{launcher.name} exists — embed it or delete the orphaned source file"
    )
    expected = launcher.read_bytes()
    assert any(base64.b64decode(blob) == expected for blob in blobs), (
        f"{manifest}: no base64 blob in install_cmd decodes to the committed "
        f"{launcher.name} — the embed and the source have drifted. Regenerate "
        "with: base64 < launcher.sh | tr -d '\\n' and replace the blob."
    )


_OPENCLAW_MANIFEST = _REPO_ROOT / "acp" / "openclaw" / "manifest.toml"
_OPENCLAW_SOURCE = _OPENCLAW_MANIFEST.with_name("openclaw_acp_shim.py")
_OPENCLAW_TARGET = "/opt/benchflow/bin/openclaw-acp-shim"
_OPENCLAW_BLOB_RE = re.compile(
    rf"\becho\s+([A-Za-z0-9+/=]+)\s*\|\s*base64\s+"
    rf"(?:-d|--decode)\s*>\s*{re.escape(_OPENCLAW_TARGET)}\b"
)


def test_openclaw_manifest_identity_is_stable() -> None:
    """Guards extraction issue #1090's external OpenClaw identity contract."""
    manifest = tomllib.loads(_OPENCLAW_MANIFEST.read_text())
    assert manifest["name"] == "openclaw"
    assert manifest["aliases"] == ["openclaw"]
    assert list(dict.fromkeys(manifest["aliases"])) == manifest["aliases"]


def test_openclaw_embedded_blob_matches_canonical_source() -> None:
    """Guards extraction issue #1090 against readable/deployed shim drift."""
    install_cmd = tomllib.loads(_OPENCLAW_MANIFEST.read_text())["install_cmd"]
    blobs = _OPENCLAW_BLOB_RE.findall(install_cmd)
    assert len(blobs) == 1, (
        f"{_OPENCLAW_MANIFEST}: expected exactly one base64 write to "
        f"{_OPENCLAW_TARGET}, found {len(blobs)}"
    )
    assert base64.b64decode(blobs[0], validate=True) == _OPENCLAW_SOURCE.read_bytes(), (
        f"{_OPENCLAW_MANIFEST}: {_OPENCLAW_TARGET} payload drifted from "
        f"{_OPENCLAW_SOURCE.name}; regenerate the manifest blob"
    )

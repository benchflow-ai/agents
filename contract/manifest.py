#!/usr/bin/env python3
"""Reference loader + validator for the eve-style agent manifest (ADR-0001/0003).

Core scans a discovery dir and parses each ``agents/<name>/manifest.toml`` into an
``AgentConfig``; this is the contract's reference implementation, also usable as a
per-agent CI check that the manifest is well-formed and contract-compatible:

  from manifest import load_manifest, ManifestError, SUPPORTED_CONTRACT_MAJOR
  m = load_manifest("acp/mimo-acp/manifest.toml")   # raises ManifestError if invalid

The manifest is **data only** (validated against ``manifest_schema.json``, strict /
no unknown fields). Anything requiring code (credential files, config-file emission,
provider translation beyond a rename) lives in the agent's shim, not the manifest.
"""

from __future__ import annotations

import copy
import json
import tomllib
from pathlib import Path

import jsonschema

_SCHEMA_PATH = Path(__file__).parent / "manifest_schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text())

#: The contract MAJOR this core supports. A manifest targeting a different major is
#: rejected at discovery with a clear error (the dev BENCHFLOW_AGENTS_DIR override
#: bypasses pip pinning, so the gate must be in-band).
SUPPORTED_CONTRACT_MAJOR = 1

#: Defaults applied to a validated manifest so the loaded mapping is complete.
_DEFAULTS: dict = {
    "protocol": "acp",
    "env_mapping": {},
    "requires_env": [],
    "supports_acp_set_model": True,
    "acp_model_format": "bare",
}


class ManifestError(Exception):
    """A manifest is malformed, schema-invalid, or contract-incompatible."""


def _check_contract_version(version: str) -> None:
    try:
        major = int(version.split(".")[0])
    except (ValueError, AttributeError) as e:
        raise ManifestError(f"invalid contract_version {version!r}") from e
    if major != SUPPORTED_CONTRACT_MAJOR:
        raise ManifestError(
            f"manifest targets contract {version}; this benchflow supports "
            f"{SUPPORTED_CONTRACT_MAJOR}.x"
        )


def load_manifest(path: str | Path) -> dict:
    """Parse + validate one manifest.toml; return the normalized mapping (defaults
    applied). Raises ``ManifestError`` with a clear message on any problem."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{path}: invalid TOML: {e}") from e
    except OSError as e:
        raise ManifestError(f"{path}: cannot read: {e}") from e
    try:
        jsonschema.validate(data, _SCHEMA)
    except jsonschema.ValidationError as e:
        loc = "/".join(str(p) for p in e.absolute_path) or "<root>"
        raise ManifestError(f"{path}: schema violation at {loc}: {e.message}") from e
    _check_contract_version(data["contract_version"])
    normalized = {**copy.deepcopy(_DEFAULTS), **data}
    # JSON-Schema integer accepts an integral float (1200.0); the schema already
    # rejected non-integral values (1200.5), so coerce to a real int here.
    if "install_timeout" in normalized:
        normalized["install_timeout"] = int(normalized["install_timeout"])
    return normalized

"""Tests for the agent-manifest loader/validator (ADR-0001/0003).

Run: PYTHONPATH=. pytest test_manifest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from manifest import ManifestError, load_manifest  # noqa: E402

_MINIMAL = """\
contract_version = "1.0"
name = "x"
install_cmd = "echo install"
launch_cmd = "echo launch"
"""


def _write(tmp_path: Path, text: str) -> str:
    p = tmp_path / "manifest.toml"
    p.write_text(text)
    return str(p)


def test_loads_minimal_valid_manifest(tmp_path: Path) -> None:
    m = load_manifest(_write(tmp_path, _MINIMAL))
    assert m["name"] == "x"
    # defaults applied for the data-only loader
    assert m["protocol"] == "acp"
    assert m["env_mapping"] == {}
    assert m["acp_model_format"] == "bare"


def test_accepts_optional_patch_version(tmp_path: Path) -> None:
    # contract_version is SemVer MAJOR.MINOR[.PATCH]; the gate keys on MAJOR
    m = load_manifest(_write(tmp_path, _MINIMAL.replace('"1.0"', '"1.2.3"')))
    assert m["contract_version"] == "1.2.3"


def test_data_overrides_defaults(tmp_path: Path) -> None:
    text = (
        _MINIMAL + '\n[env_mapping]\nBENCHFLOW_PROVIDER_BASE_URL = "OPENAI_BASE_URL"\n'
    )
    m = load_manifest(_write(tmp_path, text))
    assert m["env_mapping"] == {"BENCHFLOW_PROVIDER_BASE_URL": "OPENAI_BASE_URL"}


def test_loaded_defaults_are_not_shared_across_loads(tmp_path: Path) -> None:
    # a manifest without env_mapping/requires_env must get FRESH default mutables;
    # mutating one load's defaults must not corrupt the module default for the next.
    first = load_manifest(_write(tmp_path, _MINIMAL))
    first["env_mapping"]["leaked"] = "x"
    first["requires_env"].append("LEAKED")

    second = load_manifest(_write(tmp_path, _MINIMAL))
    assert second["env_mapping"] == {}
    assert second["requires_env"] == []


# ── validation: every malformed/incompatible manifest must raise clearly ──


def test_rejects_missing_required_field(tmp_path: Path) -> None:
    text = _MINIMAL.replace('launch_cmd = "echo launch"\n', "")
    with pytest.raises(ManifestError, match="launch_cmd"):
        load_manifest(_write(tmp_path, text))


def test_rejects_unknown_field(tmp_path: Path) -> None:
    # additionalProperties:false — an unknown field is a typo/contract drift, reject it
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, _MINIMAL + "bogus_field = 1\n"))


def test_rejects_non_acp_protocol(tmp_path: Path) -> None:
    # one protocol (ADR-0001): session-factory and friends are gone
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, _MINIMAL + 'protocol = "session-factory"\n'))


def test_rejects_incompatible_contract_major(tmp_path: Path) -> None:
    text = _MINIMAL.replace('"1.0"', '"2.0"')
    with pytest.raises(ManifestError, match="supports 1.x"):
        load_manifest(_write(tmp_path, text))


def test_rejects_malformed_contract_version(tmp_path: Path) -> None:
    text = _MINIMAL.replace('"1.0"', '"v1"')  # fails the schema MAJOR.MINOR pattern
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, text))


def test_rejects_version_without_minor(tmp_path: Path) -> None:
    # "1" would pass the MAJOR int-parse gate, so this isolates the schema pattern:
    # the contract is MAJOR.MINOR[.PATCH], a bare major is invalid.
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, _MINIMAL.replace('"1.0"', '"1"')))


def test_install_timeout_integral_float_coerced_to_int(tmp_path: Path) -> None:
    # a TOML float with zero fractional part is integral under JSON-Schema; the
    # loader coerces it to a real int (non-integral floats still reject at schema).
    m = load_manifest(_write(tmp_path, _MINIMAL + "install_timeout = 1200.0\n"))
    assert m["install_timeout"] == 1200
    assert isinstance(m["install_timeout"], int)


def test_rejects_non_string_env_mapping_value(tmp_path: Path) -> None:
    text = _MINIMAL + "\n[env_mapping]\nBENCHFLOW_PROVIDER_API_KEY = 123\n"
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, text))


def test_rejects_bad_acp_model_format(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(_write(tmp_path, _MINIMAL + 'acp_model_format = "weird"\n'))


def test_rejects_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="invalid TOML"):
        load_manifest(_write(tmp_path, 'name = "x\n'))  # unterminated string


def test_missing_file_raises_manifest_error(tmp_path: Path) -> None:
    # core's discovery scan must see ManifestError (not a bare OSError) for an
    # absent/unreadable manifest, per the docstring contract.
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "nope.toml")


# ── the first real manifest in the repo validates against the contract ──


def test_repo_manifests_validate() -> None:
    """Every <category>/<name>/manifest.toml shipped in the repo (e.g. acp/<name>/) must load clean."""
    repo_root = Path(__file__).resolve().parents[1]
    manifests = sorted(
        {*repo_root.glob("*/manifest.toml"), *repo_root.glob("*/*/manifest.toml")}
    )
    if not manifests:
        pytest.skip("no agent manifests in the repo yet")
    for mf in manifests:
        m = load_manifest(mf)
        assert m["name"], f"{mf}: empty name"
        assert m["protocol"] == "acp", f"{mf}: not an ACP agent"

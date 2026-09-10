"""Tests for the file-backed channel source (``loaders.load_manifest_file``).

This is the facility-neutral seam: a facility that does not use the built-in
generated manifest supplies a ``{"channels": [...]}`` JSON file carrying the
same per-channel schema ``build_manifest()`` produces. Pure-python and
file-level -- no softioc, no lattice, no CA.

Two schemas load: the current one (``path`` / ``pair_key`` / ``role``) and
the six-key one the manifest carried before the channel grammar, which is
normalized into the current one on the way in so an older facility file keeps
booting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from osprey.services.virtual_accelerator.manifest import (
    LEGACY_MANIFEST_CHANNEL_KEYS,
    MANIFEST_CHANNEL_KEYS,
    ROLE_NONE,
    ROLE_READBACK,
    ROLE_SETPOINT,
    ManifestFileError,
    channel_from_legacy,
    load_manifest_file,
)


def _channel_entry(address: str, **overrides) -> dict:
    """One schema-complete manifest channel entry, in the current schema. The
    defaults describe a three-part-address facility whose identity rides in
    ``path`` under its own level names, not in the address text."""
    entry = {
        "address": address,
        "path": {"experiment": "ZZEXP", "device": "CAM01", "signal": "EXPOSURE"},
        "pair_key": "",
        "role": ROLE_NONE,
        "partition": "static-noisy",
        "record_type": "ai",
        "noise": True,
    }
    entry.update(overrides)
    return entry


def _legacy_entry(address: str, **overrides) -> dict:
    """One entry in the pre-grammar six-key schema."""
    entry = {
        "address": address,
        "ring": "ZZEXP",
        "system": "DIAG",
        "family": "CAM",
        "device": "01",
        "field": "EXPOSURE",
        "subfield": "RB",
        "partition": "static-noisy",
        "record_type": "ai",
        "noise": True,
    }
    entry.update(overrides)
    return entry


def _write_manifest(tmp_path, channels) -> Path:
    path = tmp_path / "channels_manifest.json"
    path.write_text(json.dumps({"channels": channels}))
    return path


class TestLoadManifestFile:
    def test_loads_channels_from_valid_file(self, tmp_path):
        channels = [
            _channel_entry("ZZEXP:CAM01:EXPOSURE"),
            _channel_entry(
                "ZZEXP:CAM01:EXPOSURE:SP",
                pair_key="ZZEXP:CAM01:EXPOSURE",
                role=ROLE_SETPOINT,
                partition="sp-echo",
            ),
        ]
        loaded = load_manifest_file(_write_manifest(tmp_path, channels))
        assert loaded == channels

    def test_any_level_names_load_without_grammar_constraint(self, tmp_path):
        # The seam imposes no address grammar and no level names: a facility
        # whose real PV names are three-part strings, keyed by levels of its
        # own, loads through the same call.
        channels = [_channel_entry("ZZEXP:JET:PRESSURE", path={"jet": "JET", "q": "PRESSURE"})]
        loaded = load_manifest_file(_write_manifest(tmp_path, channels))
        assert loaded[0]["address"] == "ZZEXP:JET:PRESSURE"
        assert loaded[0]["path"] == {"jet": "JET", "q": "PRESSURE"}

    def test_missing_file_raises_named_error(self, tmp_path):
        with pytest.raises(ManifestFileError, match="not found"):
            load_manifest_file(tmp_path / "absent.json")

    def test_invalid_json_raises_named_error(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json")
        with pytest.raises(ManifestFileError, match="not valid JSON"):
            load_manifest_file(path)

    def test_top_level_must_carry_a_channels_list(self, tmp_path):
        path = tmp_path / "shapeless.json"
        path.write_text(json.dumps({"pvs": []}))
        with pytest.raises(ManifestFileError, match="'channels' list"):
            load_manifest_file(path)

    def test_channel_missing_schema_keys_is_named_in_the_error(self, tmp_path):
        incomplete = _channel_entry("ZZEXP:CAM02:EXPOSURE")
        del incomplete["partition"], incomplete["noise"]
        with pytest.raises(ManifestFileError, match="noise, partition"):
            load_manifest_file(_write_manifest(tmp_path, [incomplete]))

    def test_duplicate_address_raises(self, tmp_path):
        dup = _channel_entry("ZZEXP:CAM03:EXPOSURE")
        with pytest.raises(ManifestFileError, match="duplicate address"):
            load_manifest_file(_write_manifest(tmp_path, [dup, dict(dup)]))

    def test_empty_address_raises(self, tmp_path):
        with pytest.raises(ManifestFileError, match="empty address"):
            load_manifest_file(_write_manifest(tmp_path, [_channel_entry("")]))

    def test_unknown_role_raises(self, tmp_path):
        with pytest.raises(ManifestFileError, match="role 'writer'"):
            load_manifest_file(_write_manifest(tmp_path, [_channel_entry("A", role="writer")]))

    def test_role_without_pair_key_raises(self, tmp_path):
        with pytest.raises(ManifestFileError, match="no 'pair_key'"):
            load_manifest_file(_write_manifest(tmp_path, [_channel_entry("A", role=ROLE_SETPOINT)]))

    def test_path_must_map_levels_to_strings(self, tmp_path):
        with pytest.raises(ManifestFileError, match="'path' must be an object"):
            load_manifest_file(_write_manifest(tmp_path, [_channel_entry("A", path={"device": 1})]))

    def test_schema_keys_match_serving_consumption(self):
        # The documented schema is exactly what serving/pvdb.py reads off
        # each channel dict -- keep the frozen set honest against the
        # factory's field accesses.
        assert MANIFEST_CHANNEL_KEYS == {
            "address",
            "path",
            "pair_key",
            "role",
            "partition",
            "record_type",
            "noise",
        }


class TestLegacySchema:
    """The six-key schema still loads, normalized into the current one."""

    def test_legacy_keys_are_the_pre_grammar_schema(self):
        assert LEGACY_MANIFEST_CHANNEL_KEYS == {
            "address",
            "ring",
            "system",
            "family",
            "device",
            "field",
            "subfield",
            "partition",
            "record_type",
            "noise",
        }

    def test_legacy_pair_is_normalized_onto_one_pair_key(self, tmp_path):
        channels = [
            _legacy_entry("ZZEXP:DIAG:CAM:01:EXPOSURE:SP", subfield="SP", partition="sp-echo"),
            _legacy_entry("ZZEXP:DIAG:CAM:01:EXPOSURE:RB", subfield="RB", partition="sp-echo"),
        ]
        setpoint, readback = load_manifest_file(_write_manifest(tmp_path, channels))
        assert set(setpoint) == MANIFEST_CHANNEL_KEYS
        assert setpoint["role"] == ROLE_SETPOINT
        assert readback["role"] == ROLE_READBACK
        # Paired on the five identity keys plus the setpoint token: the
        # setpoint's own address, in the reference facility's spelling.
        assert setpoint["pair_key"] == readback["pair_key"] == "ZZEXP:DIAG:CAM:01:EXPOSURE:SP"
        assert setpoint["path"] == {
            "ring": "ZZEXP",
            "system": "DIAG",
            "family": "CAM",
            "device": "01",
            "field": "EXPOSURE",
            "subfield": "SP",
        }

    def test_legacy_channel_outside_a_pair_has_no_role(self):
        normalized = channel_from_legacy(_legacy_entry("ZZEXP:DIAG:CAM:01:POS:X", subfield="X"))
        assert normalized["role"] == ROLE_NONE
        assert normalized["pair_key"] == ""
        assert normalized["partition"] == "static-noisy"

    def test_legacy_and_current_entries_may_share_one_file(self, tmp_path):
        channels = [_legacy_entry("ZZEXP:DIAG:CAM:01:EXPOSURE:RB"), _channel_entry("ZZEXP:JET:P")]
        loaded = load_manifest_file(_write_manifest(tmp_path, channels))
        assert [set(c) for c in loaded] == [MANIFEST_CHANNEL_KEYS, MANIFEST_CHANNEL_KEYS]

    def test_legacy_entry_missing_keys_is_named_against_the_current_schema(self, tmp_path):
        # Missing keys in both schemas: the error names the current schema's,
        # which is the one to write a new file against.
        incomplete = _legacy_entry("ZZEXP:DIAG:CAM:02:EXPOSURE:RB")
        del incomplete["partition"], incomplete["noise"]
        with pytest.raises(ManifestFileError, match="noise, pair_key, partition, path, role"):
            load_manifest_file(_write_manifest(tmp_path, [incomplete]))

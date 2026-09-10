"""The channel grammar: a manifest from any declared hierarchy, not the ring's six.

The virtual accelerator used to read the six level names of the reference
facility (``ring``/``system``/``family``/``device``/``field``/``subfield``)
off every hierarchy path by name, and paired a setpoint with its readback on
the ``SP``/``RB`` tokens of the last one. A facility whose hierarchical
database declares other levels stopped ``osprey build`` with
``KeyError: 'ring'``.

These tests pin the replacement: the database declares its levels and,
beside them, which level tells a setpoint from its readback and by which
token pairs (``hierarchy.pairing``); the manifest is built against that
grammar; and the serving layer pairs on the ``pair_key`` / ``role`` the
manifest carries, never on a level name. The second-facility fixture is
shaped like a single-pass injector: five levels joined with no separator,
magnets pairing ``.S`` with ``M``, RF pairing ``GSET`` with ``GMES`` and
``PSET`` with ``PMES`` on the same cavity, a gun pairing ``Preset_Volt`` with
``HVPSkVolts``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from osprey.errors import BuildProfileError
from osprey.services.channel_finder.databases.channel_grammar import (
    BUILTIN_GRAMMAR,
    BUILTIN_LEVELS,
    ROLE_NONE,
    ROLE_READBACK,
    ROLE_SETPOINT,
    ChannelGrammar,
    GrammarError,
)
from osprey.services.channel_finder.databases.hierarchical import HierarchicalChannelDatabase
from osprey.services.virtual_accelerator.manifest import (
    PARTITION_PYAT_COUPLED,
    PARTITION_SP_ECHO,
    PARTITION_STATIC_NOISY,
    RECORD_TYPE_ANALOG,
    RECORD_TYPE_BINARY,
    classify_partition,
    derive_record_type,
)
from osprey.services.virtual_accelerator.manifest.build import (
    build_manifest,
    prepare_project_manifest,
)
from osprey.services.virtual_accelerator.manifest.paths import ManifestPaths
from osprey.services.virtual_accelerator.serving.pvdb import (
    ManifestContractError,
    build_serving_pvdb,
)

INJECTOR_LEVELS = ["system", "family", "sector", "device", "property"]

INJECTOR_PAIRING = {
    "level": "property",
    "pairs": [
        {"setpoint": ".S", "readback": "M", "where": {"system": ["M"]}},
        {"setpoint": "GSET", "readback": "GMES"},
        {"setpoint": "PSET", "readback": "PMES"},
        {"setpoint": "Preset_Volt", "readback": "HVPSkVolts"},
        # Declared, but the fixture serves no readback for it: a lone half.
        {"setpoint": "S", "readback": "SRB", "where": {"system": ["V"]}},
    ],
}


def _leaf(description: str) -> dict:
    return {"_description": description}


def _injector_database(pairing: dict | None = INJECTOR_PAIRING) -> dict:
    """A compact second-facility hierarchical database.

    Fifteen channels: two quadrupoles (setpoint, measured current, integrated
    field), one cavity (gradient and phase pairs plus a forward power), the
    gun (voltage pair plus tank pressure) and one valve (a setpoint whose
    readback is declared but not served).
    """
    hierarchy: dict = {
        "levels": [
            {"name": "system", "type": "tree"},
            {"name": "family", "type": "tree"},
            {"name": "sector", "type": "tree"},
            {"name": "device", "type": "instances"},
            {"name": "property", "type": "tree"},
        ],
        "naming_pattern": "{system}{family}{sector}{device}{property}",
    }
    if pairing is not None:
        hierarchy["pairing"] = pairing
    return {
        "hierarchy": hierarchy,
        "tree": {
            "M": {
                "_description": "Magnets",
                "QJ": {
                    "_description": "Quadrupoles",
                    "M5": {
                        "_description": "MeV sector 5",
                        "DEVICE": {
                            "_expansion": {
                                "_type": "range",
                                "_pattern": "{:02d}",
                                "_range": [1, 2],
                            },
                            ".S": _leaf("current setpoint"),
                            "M": _leaf("current measured"),
                            ".BDL": _leaf("integrated field"),
                        },
                    },
                },
            },
            "R": {
                "_description": "RF",
                "K": {
                    "_description": "Cavities",
                    "3": {
                        "_description": "cryomodule 3",
                        "DEVICE": {
                            "_expansion": {"_type": "list", "_instances": ["1"]},
                            "GSET": _leaf("gradient setpoint"),
                            "GMES": _leaf("gradient measured"),
                            "PSET": _leaf("phase setpoint"),
                            "PMES": _leaf("phase measured"),
                            "CRFP": _leaf("forward power"),
                        },
                    },
                },
            },
            "I": {
                "_description": "Instrumentation",
                "GL": {
                    "_description": "Gun",
                    "K1": {
                        "_description": "keV sector 1",
                        "DEVICE": {
                            "_expansion": {"_type": "list", "_instances": ["00"]},
                            "Preset_Volt": _leaf("HVPS voltage setpoint"),
                            "HVPSkVolts": _leaf("HVPS voltage"),
                            "TANKPSI": _leaf("tank pressure"),
                        },
                    },
                },
            },
            "V": {
                "_description": "Vacuum",
                "BV": {
                    "_description": "Beamline valves",
                    "M1": {
                        "_description": "MeV sector 1",
                        "DEVICE": {
                            "_expansion": {"_type": "list", "_instances": ["01"]},
                            "S": _leaf("valve command"),
                        },
                    },
                },
            },
        },
    }


def _stage_tree(data_root: Path, database: dict) -> ManifestPaths:
    """Write a data tree the manifest generator reads: the database at tier 3
    plus the three per-tree sources, all empty of demo content."""
    tier = data_root / "channel_databases" / "tiers" / "tier3"
    tier.mkdir(parents=True)
    (tier / "hierarchical.json").write_text(json.dumps(database))
    (data_root / "simulation").mkdir()
    (data_root / "simulation" / "machine.json").write_text(
        json.dumps({"name": "injector", "description": "fixture", "channels": {}})
    )
    (data_root / "machine_state_channels.json").write_text(json.dumps({"_version": "2.0"}))
    (data_root / "channel_limits.json").write_text(json.dumps({"_version": "4.0", "defaults": {}}))
    return ManifestPaths(data_root=data_root, tier=3)


@pytest.fixture()
def injector_tree(tmp_path: Path) -> ManifestPaths:
    return _stage_tree(tmp_path, _injector_database())


@pytest.fixture()
def injector_manifest(injector_tree: ManifestPaths) -> dict:
    return build_manifest(injector_tree)


class TestGrammarFromHierarchy:
    def test_builtin_levels_get_the_reference_convention_by_default(self):
        grammar = ChannelGrammar.from_hierarchy(BUILTIN_LEVELS)
        assert grammar.is_builtin
        assert grammar.pairing_level == "subfield"
        assert [(p.setpoint, p.readback) for p in grammar.pairs] == [("SP", "RB")]
        assert grammar.declared is False
        assert grammar.identity_levels == ("ring", "system", "family", "device", "field")
        assert grammar.qualifier_level == "field"

    def test_other_levels_without_a_pairing_block_declare_no_pairs(self):
        grammar = ChannelGrammar.from_hierarchy(INJECTOR_LEVELS)
        assert not grammar.is_builtin
        assert grammar.pairing_level == "property"
        assert grammar.pairs == ()
        assert grammar.pairing({"system": "M", "property": ".S"}) is None

    def test_declared_pairing_block_is_read(self):
        grammar = ChannelGrammar.from_hierarchy(INJECTOR_LEVELS, INJECTOR_PAIRING)
        assert grammar.declared
        assert grammar.pairing_level == "property"
        assert len(grammar.pairs) == 5
        assert grammar.pairs[0].where == {"system": frozenset({"M"})}
        assert grammar.as_json()["pairs"][0] == {
            "setpoint": ".S",
            "readback": "M",
            "where": {"system": ["M"]},
        }

    def test_pairing_level_defaults_to_the_last_level(self):
        grammar = ChannelGrammar.from_hierarchy(
            INJECTOR_LEVELS, {"pairs": [{"setpoint": "GSET", "readback": "GMES"}]}
        )
        assert grammar.pairing_level == "property"

    @pytest.mark.parametrize(
        ("pairing", "message"),
        [
            ("SP/RB", "must be an object"),
            ({"tokens": []}, "unknown key"),
            ({"level": "field", "pairs": [{"setpoint": "a", "readback": "b"}]}, "not a declared"),
            ({"pairs": []}, "non-empty list"),
            ({"pairs": ["SP"]}, "must be an object with 'setpoint' and 'readback'"),
            ({"pairs": [{"setpoint": "SP"}]}, "non-empty string 'readback'"),
            ({"pairs": [{"setpoint": "SP", "readback": "SP"}]}, "same token"),
            ({"pairs": [{"setpoint": "a", "readback": "b", "rb": 1}]}, "unknown key"),
            (
                {"pairs": [{"setpoint": "a", "readback": "b", "where": {"ring": ["SR"]}}]},
                "not a declared",
            ),
            (
                {"pairs": [{"setpoint": "a", "readback": "b", "where": {"system": []}}]},
                "non-empty list of strings",
            ),
        ],
    )
    def test_malformed_pairing_blocks_are_refused_by_name(self, pairing, message):
        with pytest.raises(GrammarError, match=message):
            ChannelGrammar.from_hierarchy(INJECTOR_LEVELS, pairing)

    def test_the_database_loader_refuses_a_malformed_block_at_load(self, tmp_path: Path):
        path = tmp_path / "hierarchical.json"
        path.write_text(json.dumps(_injector_database(pairing={"pairs": []})))
        with pytest.raises(ValueError, match="hierarchy.pairing"):
            HierarchicalChannelDatabase(str(path)).load_database()

    def test_the_database_carries_its_grammar(self, tmp_path: Path):
        path = tmp_path / "hierarchical.json"
        path.write_text(json.dumps(_injector_database()))
        db = HierarchicalChannelDatabase(str(path))
        db.load_database()
        assert db.grammar.levels == tuple(INJECTOR_LEVELS)
        assert db.grammar.declared


class TestPairing:
    grammar = ChannelGrammar.from_hierarchy(INJECTOR_LEVELS, INJECTOR_PAIRING)

    def test_setpoint_and_readback_share_one_pair_key(self):
        quad = {"system": "M", "family": "QJ", "sector": "M5", "device": "01"}
        setpoint = self.grammar.pairing({**quad, "property": ".S"})
        readback = self.grammar.pairing({**quad, "property": "M"})
        assert setpoint.role == ROLE_SETPOINT and readback.role == ROLE_READBACK
        assert setpoint.pair_key == readback.pair_key == "M:QJ:M5:01:.S"
        assert setpoint.counterpart == "M" and readback.counterpart == ".S"

    def test_two_pairs_on_one_device_key_apart(self):
        cavity = {"system": "R", "family": "K", "sector": "3", "device": "1"}
        gradient = self.grammar.pairing({**cavity, "property": "GMES"})
        phase = self.grammar.pairing({**cavity, "property": "PMES"})
        assert gradient.pair_key == "R:K:3:1:GSET"
        assert phase.pair_key == "R:K:3:1:PSET"

    def test_where_restricts_a_pair(self):
        # ``M`` is a readback on a magnet and nothing on a valve.
        assert self.grammar.pairing({"system": "V", "property": "M"}) is None
        assert self.grammar.pairing({"system": "M", "property": "M"}).role == ROLE_READBACK

    def test_unclaimed_token_is_in_no_pair(self):
        assert self.grammar.pairing({"system": "M", "property": ".BDL"}) is None

    def test_ambiguous_claim_is_refused(self):
        grammar = ChannelGrammar.from_hierarchy(
            INJECTOR_LEVELS,
            {
                "pairs": [
                    {"setpoint": "S", "readback": "M"},
                    {"setpoint": "S", "readback": "R"},
                ]
            },
        )
        with pytest.raises(GrammarError, match="claimed by 2 declared pairs"):
            grammar.pairing({"system": "M", "property": "S"})

    def test_builtin_pair_key_is_the_setpoint_address(self):
        path = {
            "ring": "SR",
            "system": "MAG",
            "family": "HCM",
            "device": "01",
            "field": "CURRENT",
            "subfield": "RB",
        }
        assert BUILTIN_GRAMMAR.pairing(path).pair_key == "SR:MAG:HCM:01:CURRENT:SP"


class TestClassification:
    def test_builtin_grammar_keeps_the_spec_rules(self):
        path = {
            "ring": "SR",
            "system": "MAG",
            "family": "HCM",
            "device": "01",
            "field": "CURRENT",
            "subfield": "SP",
        }
        assert classify_partition(path) == PARTITION_PYAT_COUPLED
        assert classify_partition(path, BUILTIN_GRAMMAR) == PARTITION_PYAT_COUPLED

    def test_other_grammar_is_partitioned_by_role_alone(self):
        grammar = ChannelGrammar.from_hierarchy(INJECTOR_LEVELS, INJECTOR_PAIRING)
        path = {"system": "M", "family": "QJ", "sector": "M5", "device": "01", "property": ".S"}
        assert (
            classify_partition(path, grammar, role=ROLE_SETPOINT, counterpart_served=True)
            == PARTITION_SP_ECHO
        )
        assert (
            classify_partition(path, grammar, role=ROLE_SETPOINT, counterpart_served=False)
            == PARTITION_STATIC_NOISY
        )
        assert classify_partition(path, grammar, role=ROLE_NONE) == PARTITION_STATIC_NOISY

    def test_record_type_reads_the_pairing_level_and_its_qualifier(self):
        grammar = ChannelGrammar.from_hierarchy(INJECTOR_LEVELS, INJECTOR_PAIRING)
        assert derive_record_type({"device": "01", "property": "GSET"}, grammar) == (
            RECORD_TYPE_ANALOG,
            True,
        )
        assert derive_record_type({"device": "STATUS", "property": "x"}, grammar) == (
            RECORD_TYPE_BINARY,
            False,
        )
        assert derive_record_type({"device": "01", "property": "FAULT"}, grammar) == (
            RECORD_TYPE_BINARY,
            False,
        )


class TestInjectorManifest:
    """The second-facility fixture builds, pairs and serves on its own names."""

    def test_every_channel_carries_its_declared_path(self, injector_manifest):
        assert injector_manifest["_metadata"]["total_channels"] == 15
        for channel in injector_manifest["channels"]:
            assert list(channel["path"]) == INJECTOR_LEVELS
            assert "ring" not in channel

    def test_the_grammar_and_census_are_published(self, injector_manifest):
        metadata = injector_manifest["_metadata"]
        assert metadata["grammar"]["levels"] == INJECTOR_LEVELS
        assert metadata["grammar"]["pairing_level"] == "property"
        assert metadata["grammar"]["pairing_declared"] is True
        assert metadata["by_top_level"] == {
            "level": "system",
            "counts": {"I": 3, "M": 6, "R": 5, "V": 1},
        }
        # Five pairs plus the valve's lone setpoint: a role is the grammar's
        # word, counted whether or not the other half is served.
        assert metadata["setpoint_count"] == 6

    def test_declared_pairs_become_echo_pairs(self, injector_manifest):
        by_address = {c["address"]: c for c in injector_manifest["channels"]}
        pairs = {
            ("MQJM501.S", "MQJM501M"),
            ("MQJM502.S", "MQJM502M"),
            ("RK31GSET", "RK31GMES"),
            ("RK31PSET", "RK31PMES"),
            ("IGLK100Preset_Volt", "IGLK100HVPSkVolts"),
        }
        for setpoint, readback in pairs:
            assert by_address[setpoint]["role"] == ROLE_SETPOINT
            assert by_address[readback]["role"] == ROLE_READBACK
            assert by_address[setpoint]["pair_key"] == by_address[readback]["pair_key"]
            assert by_address[setpoint]["partition"] == PARTITION_SP_ECHO
            assert by_address[readback]["partition"] == PARTITION_SP_ECHO
        assert by_address["RK31GSET"]["pair_key"] != by_address["RK31PSET"]["pair_key"]
        assert injector_manifest["_metadata"]["by_partition"] == {
            PARTITION_SP_ECHO: 10,
            PARTITION_STATIC_NOISY: 5,
        }

    def test_nothing_is_pyat_coupled_outside_the_builtin_grammar(self, injector_manifest):
        assert all(c["partition"] != PARTITION_PYAT_COUPLED for c in injector_manifest["channels"])

    def test_a_lone_half_keeps_its_role_but_is_not_an_echo_pair(self, injector_manifest):
        by_address = {c["address"]: c for c in injector_manifest["channels"]}
        valve = by_address["VBVM101S"]
        assert valve["role"] == ROLE_SETPOINT
        assert valve["pair_key"] == "V:BV:M1:01:S"
        assert valve["partition"] == PARTITION_STATIC_NOISY

    def test_unclaimed_channels_are_static_noisy_with_no_role(self, injector_manifest):
        by_address = {c["address"]: c for c in injector_manifest["channels"]}
        for address in ("MQJM501.BDL", "RK31CRFP", "IGLK100TANKPSI"):
            assert by_address[address]["role"] == ROLE_NONE
            assert by_address[address]["pair_key"] == ""
            assert by_address[address]["partition"] == PARTITION_STATIC_NOISY

    def test_the_serving_layer_pairs_on_the_manifest_alone(self, injector_manifest):
        records = build_serving_pvdb(injector_manifest["channels"])
        assert len(records.all) == 15
        assert records.setpoint_readbacks == {
            "MQJM501.S": "MQJM501M",
            "MQJM502.S": "MQJM502M",
            "RK31GSET": "RK31GMES",
            "RK31PSET": "RK31PMES",
            "IGLK100Preset_Volt": "IGLK100HVPSkVolts",
        }
        assert set(records.setpoints) == set(records.setpoint_readbacks) | {"VBVM101S"}
        assert not records.pyat_coupled

    def test_without_a_pairing_block_nothing_pairs_and_the_build_says_so(self, tmp_path: Path):
        manifest = build_manifest(_stage_tree(tmp_path, _injector_database(pairing=None)))
        metadata = manifest["_metadata"]
        assert metadata["grammar"]["pairs"] == []
        assert metadata["grammar"]["pairing_declared"] is False
        assert metadata["setpoint_count"] == 0
        assert metadata["by_partition"] == {PARTITION_STATIC_NOISY: 15}

    def test_the_build_time_generator_prepares_it(self, tmp_path: Path):
        paths = _stage_tree(tmp_path, _injector_database())
        prepared = prepare_project_manifest(paths.data_root, 3)
        assert prepared is not None
        assert prepared.manifest["_metadata"]["total_channels"] == 15

    def test_an_ambiguous_declaration_stops_the_build_by_name(self, tmp_path: Path):
        ambiguous = {
            "pairs": [
                {"setpoint": ".S", "readback": "M"},
                {"setpoint": ".S", "readback": ".BDL"},
            ]
        }
        paths = _stage_tree(tmp_path, _injector_database(pairing=ambiguous))
        with pytest.raises(BuildProfileError, match="'hierarchy.pairing' declaration is ambiguous"):
            prepare_project_manifest(paths.data_root, 3)


class TestServingContract:
    def test_a_role_without_a_pair_key_is_refused(self):
        channel = {
            "address": "A",
            "path": {},
            "pair_key": "",
            "role": ROLE_SETPOINT,
            "partition": PARTITION_STATIC_NOISY,
            "record_type": RECORD_TYPE_ANALOG,
            "noise": False,
        }
        with pytest.raises(ManifestContractError, match="no pair_key"):
            build_serving_pvdb([channel])

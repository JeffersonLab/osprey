"""Namespace-union manifest generator for the PyAT virtual accelerator.

A deployment's channel-finder databases already define the channel namespace
the virtual accelerator must serve: the tutorial ships three interchangeable
file "paradigm" formats (in_context, hierarchical, middle_layer) that describe
the same set of PV addresses, and a facility of its own stages whichever of
them it has. The ``graph`` paradigm is deliberately not among them -- it
answers from a seeded store rather than a tier file, so it contributes no
manifest source.

The hierarchical database is the one that declares a *grammar*: the levels
every address is composed of, and -- through its ``hierarchy.pairing`` block
-- which level tells a setpoint from its readback and by which tokens
(:mod:`osprey.services.channel_finder.databases.channel_grammar`). The
manifest is built against that grammar, whatever levels the database names,
so a facility whose addresses are not spelled like the reference facility's
``{ring}:{system}:{family}:{device}:{field}:{subfield}`` is served on its own
names.

This package expands the staged file formats at their build-resolved tier,
verifies they agree, unions in the scenario-seed ``machine.json`` channels,
reconciles the machine-state template against the result, and classifies
every address into a physics-fidelity partition (pyat-coupled / sp-echo /
static-noisy) plus an EPICS record type. The served channel set is derived
from these sources -- never hand-listed.

See :func:`build.build_manifest` for the entry point.
"""

from osprey.services.channel_finder.databases.channel_grammar import (
    BUILTIN_GRAMMAR,
    ROLE_NONE,
    ROLE_READBACK,
    ROLE_SETPOINT,
    ROLES,
    ChannelGrammar,
    GrammarError,
)

from .build import build_manifest
from .classify import (
    PARTITION_PYAT_COUPLED,
    PARTITION_SP_ECHO,
    PARTITION_STATIC_NOISY,
    RECORD_TYPE_ANALOG,
    RECORD_TYPE_BINARY,
    RECORD_TYPE_LONG_STRING,
    RECORD_TYPE_MBB,
    RECORD_TYPE_STRING,
    classify_partition,
    derive_record_type,
)
from .loaders import (
    LEGACY_MANIFEST_CHANNEL_KEYS,
    MANIFEST_CHANNEL_KEYS,
    ManifestFileError,
    channel_from_legacy,
    load_manifest_file,
)

__all__ = [
    "build_manifest",
    "channel_from_legacy",
    "classify_partition",
    "derive_record_type",
    "load_manifest_file",
    "BUILTIN_GRAMMAR",
    "ChannelGrammar",
    "GrammarError",
    "ManifestFileError",
    "LEGACY_MANIFEST_CHANNEL_KEYS",
    "MANIFEST_CHANNEL_KEYS",
    "PARTITION_PYAT_COUPLED",
    "PARTITION_SP_ECHO",
    "PARTITION_STATIC_NOISY",
    "RECORD_TYPE_ANALOG",
    "RECORD_TYPE_BINARY",
    "RECORD_TYPE_LONG_STRING",
    "RECORD_TYPE_MBB",
    "RECORD_TYPE_STRING",
    "ROLE_NONE",
    "ROLE_READBACK",
    "ROLE_SETPOINT",
    "ROLES",
]

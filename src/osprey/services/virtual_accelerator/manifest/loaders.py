"""Loads and normalizes the paradigm channel DBs plus the scenario data sources.

Reuses osprey's own channel_finder database parsers (the same code that
loads these files at runtime) so this generator never re-implements
``_expansion`` range/list parsing. Note the IOC does *not* read the emitted
``channel_manifest.json``: ``entrypoint.py`` regenerates the manifest
in-process via ``build_manifest()``, and the committed JSON serves only as a
drift guard. (An IOC *can* be pointed at a manifest JSON explicitly -- that
is the file-backed channel source below, :func:`load_manifest_file`.)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from osprey.services.channel_finder.databases.channel_grammar import (
    BUILTIN_GRAMMAR,
    BUILTIN_READBACK_TOKEN,
    BUILTIN_SETPOINT_TOKEN,
    PAIR_KEY_SEPARATOR,
    ROLE_NONE,
    ROLE_READBACK,
    ROLE_SETPOINT,
    ROLES,
    ChannelGrammar,
)
from osprey.services.channel_finder.databases.hierarchical import (
    HierarchicalChannelDatabase,
)
from osprey.services.channel_finder.databases.middle_layer import MiddleLayerDatabase
from osprey.services.channel_finder.databases.template import (
    ChannelDatabase as TemplateChannelDatabase,
)

from .paths import PACKAGE_PATHS, ManifestPaths


@dataclass(frozen=True)
class HierarchicalChannel:
    """One expanded address plus its decomposed hierarchy path.

    ``path`` maps the hierarchy level names the database declares (the
    reference facility's ring/system/family/device/field/subfield, or any
    other facility's own) to the value selected for this channel, as produced
    by HierarchicalChannelDatabase's tree expansion.
    """

    address: str
    path: dict[str, str]


@dataclass(frozen=True)
class HierarchicalNamespace:
    """A hierarchical database's channels together with the grammar they follow.

    The grammar is what the database declared beside its levels -- which level
    tells a setpoint from its readback, and by which tokens -- and it travels
    with the channels because a path is only readable against the levels that
    named it.
    """

    channels: list[HierarchicalChannel]
    grammar: ChannelGrammar


def load_hierarchical_namespace(paths: ManifestPaths = PACKAGE_PATHS) -> HierarchicalNamespace:
    """Expand ``paths``' hierarchical DB into its channels and its grammar."""
    db = HierarchicalChannelDatabase(str(paths.hierarchical_db))
    db.load_database()
    channels = [
        HierarchicalChannel(address=ch["address"], path=ch["path"]) for ch in db.get_all_channels()
    ]
    return HierarchicalNamespace(channels=channels, grammar=db.grammar)


class ParadigmMismatchError(RuntimeError):
    """Raised when the file-backed paradigm DBs disagree on their address set.

    The whole premise of this generator is that the tutorial's channel-finder
    DBs already define a single namespace in three interchangeable file
    formats: in_context, hierarchical, middle_layer. (The ``graph`` paradigm
    has no tier file and is never read here.) A mismatch means that premise is
    broken and must be fixed upstream in the DB source files -- never silently
    reconciled here.
    """


def load_hierarchical_channels(paths: ManifestPaths = PACKAGE_PATHS) -> list[HierarchicalChannel]:
    """Expand ``paths``' hierarchical DB into (address, path) pairs."""
    return load_hierarchical_namespace(paths).channels


def load_in_context_addresses(paths: ManifestPaths = PACKAGE_PATHS) -> set[str]:
    """Expand ``paths``' in_context (flat/template) DB into an address set."""
    db = TemplateChannelDatabase(str(paths.in_context_db))
    db.load_database()
    return {ch["address"] for ch in db.get_all_channels()}


def load_middle_layer_addresses(paths: ManifestPaths = PACKAGE_PATHS) -> set[str]:
    """Expand ``paths``' middle_layer (MML) DB into an address set."""
    db = MiddleLayerDatabase(str(paths.middle_layer_db))
    db.load_database()
    return {ch["address"] for ch in db.get_all_channels()}


def load_machine_json_channels(
    path: Path | None = None, paths: ManifestPaths = PACKAGE_PATHS
) -> dict[str, dict]:
    """Return the scenario-seed machine.json channels keyed by address.

    ``path`` selects which machine.json to read: ``None`` (the default)
    reads the bundled control-assistant template's copy; a file-backed
    facility passes its own mounted
    machine.json instead (see ``entrypoint.py``). ``paths`` supplies the
    fallback for callers that anchor on a data tree rather than a single
    file (the build-time generator).
    """
    data = json.loads((path or paths.machine_json).read_text())
    channels: dict[str, dict] = data["channels"]
    return channels


# --- file-backed channel source ------------------------------------------

# The full per-channel schema the serving layer consumes -- identical to the
# in-memory shape build_manifest()["channels"] produces. A file-backed
# manifest must supply every key for every channel:
#
#   address      the PV name served
#   path         the channel's hierarchy path, keyed by the levels its
#                database declares ({} when it carries none)
#   pair_key     the identity a setpoint and its readback share -- the
#                serving layer pairs the two halves on exactly this string --
#                or "" for a channel in no pair
#   role         "setpoint", "readback", or "" (see channel_grammar.ROLES)
#   partition    pyat-coupled / sp-echo / static-noisy
#   record_type  the EPICS record type (see classify)
#   noise        whether the IOC jitters the value
MANIFEST_CHANNEL_KEYS = frozenset(
    {
        "address",
        "path",
        "pair_key",
        "role",
        "partition",
        "record_type",
        "noise",
    }
)

# The schema the manifest carried before the channel grammar: the reference
# facility's six level names as top-level keys, setpoint and readback told
# apart by ``subfield``. Still accepted from a file, and normalized into the
# schema above on load, so a facility that wrote its manifest against the
# older shape keeps booting.
LEGACY_MANIFEST_CHANNEL_KEYS = frozenset(
    {
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
)
_LEGACY_IDENTITY_KEYS = ("ring", "system", "family", "device", "field")


class ManifestFileError(RuntimeError):
    """A file-backed channel manifest is missing, unreadable, or malformed.

    Raised eagerly at load time so a misconfigured IOC dies at boot with a
    named cause, never serving a partial channel set.
    """


def channel_from_legacy(channel: dict) -> dict:
    """Normalize a six-key (pre-grammar) manifest channel into the current schema.

    The six keys become the ``path``; ``subfield`` ``SP``/``RB`` becomes the
    ``role``, and the five identity keys joined with the ``SP`` token become
    the ``pair_key`` -- exactly the pairing the serving layer used to derive
    from those keys itself. A channel whose subfield is neither is in no
    pair.
    """
    path = {level: channel[level] for level in BUILTIN_GRAMMAR.levels}
    subfield = channel["subfield"]
    if subfield == BUILTIN_SETPOINT_TOKEN:
        role = ROLE_SETPOINT
    elif subfield == BUILTIN_READBACK_TOKEN:
        role = ROLE_READBACK
    else:
        role = ROLE_NONE
    pair_key = ""
    if role != ROLE_NONE:
        pair_key = BUILTIN_GRAMMAR.identity(path) + PAIR_KEY_SEPARATOR + BUILTIN_SETPOINT_TOKEN
    return {
        "address": channel["address"],
        "path": path,
        "pair_key": pair_key,
        "role": role,
        "partition": channel["partition"],
        "record_type": channel["record_type"],
        "noise": channel["noise"],
    }


def _validate_channel_shape(path: Path, index: int, channel: dict) -> None:
    """Refuse a current-schema channel whose values cannot be served."""
    address = channel["address"]
    if not isinstance(channel["path"], dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in channel["path"].items()
    ):
        raise ManifestFileError(
            f"channel manifest {path}: channels[{index}] ({address!r}) 'path' must be an "
            "object mapping level names to strings"
        )
    if channel["role"] not in ROLES:
        raise ManifestFileError(
            f"channel manifest {path}: channels[{index}] ({address!r}) has role "
            f"{channel['role']!r}; it must be one of {sorted(ROLES)}"
        )
    if not isinstance(channel["pair_key"], str):
        raise ManifestFileError(
            f"channel manifest {path}: channels[{index}] ({address!r}) 'pair_key' must be a string"
        )
    if channel["role"] != ROLE_NONE and not channel["pair_key"]:
        raise ManifestFileError(
            f"channel manifest {path}: channels[{index}] ({address!r}) has role "
            f"{channel['role']!r} but no 'pair_key' to pair on"
        )


def load_manifest_file(path: Path) -> list[dict]:
    """Load the channel list from a manifest JSON file.

    This is the file-backed channel source: a facility that does not use the
    built-in generated manifest supplies ``{"channels": [...]}`` where each
    entry carries the exact per-channel schema ``build_manifest()`` produces
    (see ``MANIFEST_CHANNEL_KEYS``). Facility-neutral by construction -- no
    address grammar is imposed beyond the presence of the schema keys, so
    any facility's namespace (three-part addresses included) loads through
    the same call. A channel written against the older six-key schema
    (``LEGACY_MANIFEST_CHANNEL_KEYS``) is accepted and normalized.

    Raises:
        ManifestFileError: if the file is absent, not valid JSON, lacks a
            top-level ``channels`` list, contains a channel missing schema
            keys or carrying an unservable value, or declares the same
            address twice.
    """
    if not path.is_file():
        raise ManifestFileError(f"channel manifest file not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestFileError(f"channel manifest {path} is not valid JSON: {exc}") from exc

    channels = data.get("channels") if isinstance(data, dict) else None
    if not isinstance(channels, list):
        raise ManifestFileError(
            f"channel manifest {path} must be a JSON object with a 'channels' list"
        )

    loaded: list[dict] = []
    seen: set[str] = set()
    for index, channel in enumerate(channels):
        if not isinstance(channel, dict):
            raise ManifestFileError(f"channel manifest {path}: channels[{index}] is not an object")
        missing = MANIFEST_CHANNEL_KEYS - channel.keys()
        if missing and not (LEGACY_MANIFEST_CHANNEL_KEYS - channel.keys()):
            channel = channel_from_legacy(channel)
            missing = frozenset()
        if missing:
            raise ManifestFileError(
                f"channel manifest {path}: channels[{index}] "
                f"({channel.get('address', '<no address>')!r}) is missing "
                f"key(s): {', '.join(sorted(missing))}"
            )
        address = channel["address"]
        if not address:
            raise ManifestFileError(
                f"channel manifest {path}: channels[{index}] has an empty address"
            )
        if address in seen:
            raise ManifestFileError(f"channel manifest {path}: duplicate address {address!r}")
        seen.add(address)
        _validate_channel_shape(path, index, channel)
        loaded.append(channel)

    return loaded


# Matches `"<address>": { "label": ...` entries in machine_state_channels.json
_MACHINE_STATE_KEY_RE = re.compile(r'"([^"]+)":\s*\{\s*"label"')


def load_machine_state_candidate_addresses(paths: ManifestPaths = PACKAGE_PATHS) -> list[str]:
    """Extract every candidate channel key in the machine-state channel list.

    ``machine_state_channels.json`` is a plain JSON object mapping each address
    to a ``{"label": ..., "group": ...}`` entry, alongside underscore-prefixed
    metadata keys (``_comment``, ``_version``). Keying off the ``"label"``
    member picks up exactly the channel entries and skips the metadata without
    an underscore-prefix convention having to be encoded here.

    The caller (``manifest/build.py``) checks each candidate against the
    addresses the VA actually serves and publishes the split under
    ``_metadata.machine_state_reconciliation`` as ``candidates_checked`` /
    ``valid`` / ``invalid``, so an address that drifts out of the served
    namespace shows up in the manifest instead of failing silently.
    """
    text = paths.machine_state_channels.read_text()
    return _MACHINE_STATE_KEY_RE.findall(text)

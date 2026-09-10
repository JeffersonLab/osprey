"""Address partitioning and EPICS record-type derivation.

Partitions every namespace address into exactly one of three physics-
fidelity tiers the IOC treats differently:

  pyat-coupled -- backed by the AT lattice model: the SR magnet currents that
                  actually steer the beam, plus the SR BPM readbacks that
                  observe it.
  sp-echo      -- writable but physics-free: a write to the setpoint just
                  echoes onto the readback, with no lattice model behind it.
  static-noisy -- everything else: golden references, status/fault flags,
                  and slow telemetry (temperatures, pressures, radiation
                  monitors) that just needs a plausible noisy constant.

Which rules apply is decided by the channel grammar the database declares
(:mod:`osprey.services.channel_finder.databases.channel_grammar`):

* The **built-in grammar** -- the reference facility's six levels -- is the
  one the built-in facility spec (``ALS_U_AR``) describes, so its channels are
  partitioned by the spec's rules below: SR magnet currents and BPM positions
  are pyat-coupled, BR/BTS magnets and the SR RF/vacuum setpoint pairs are
  sp-echo. The lattice model exists for this grammar and no other.
* **Any other grammar** has no lattice behind it, so nothing is pyat-coupled.
  Its channels are partitioned by role alone: a setpoint or readback whose
  declared counterpart is served becomes sp-echo, everything else
  static-noisy. The declared pairs are the database's own, so no address
  spelling of the reference facility is assumed anywhere on this path.

An address is assigned to `pyat-coupled` or `sp-echo` only when it clears an
explicit rule; everything else falls through to `static-noisy`.
"""

from __future__ import annotations

from osprey.services.channel_finder.databases.channel_grammar import (
    ROLE_NONE,
    ROLE_READBACK,
    ROLE_SETPOINT,
    ChannelGrammar,
)
from osprey.simulation.facility_spec import ALS_U_AR

# Spec-derived: every magnet/corrector family declared by the facility spec
# (excludes the BPM monitor family, which is gated separately below).
MAG_FAMILIES = frozenset(f.name for f in ALS_U_AR.families if f.kind in ("magnet", "corrector"))

PARTITION_PYAT_COUPLED = "pyat-coupled"
PARTITION_SP_ECHO = "sp-echo"
PARTITION_STATIC_NOISY = "static-noisy"

# SR RF/VAC fields that carry a real writable-setpoint + readback pair.
# Pure telemetry fields in the same systems (POWER, TEMPERATURE, PRESSURE,
# ION-PUMP CURRENT) have no setpoint counterpart and stay static-noisy.
_SR_RF_VAC_SP_ECHO_FIELDS = frozenset({"VOLTAGE", "FREQUENCY", "TUNER"})


def spec_partition(path: dict[str, str]) -> str:
    """The built-in facility spec's partition rules, on a six-level path.

    Args:
        path: Hierarchy path as produced by HierarchicalChannelDatabase for
            the reference facility, mapping "ring"/"system"/"family"/
            "device"/"field"/"subfield" to the selected value.

    Returns:
        One of PARTITION_PYAT_COUPLED, PARTITION_SP_ECHO, PARTITION_STATIC_NOISY.
    """
    ring, system, family, field, subfield = (
        path["ring"],
        path["system"],
        path["family"],
        path["field"],
        path["subfield"],
    )

    if (
        ring == "SR"
        and system == "MAG"
        and family in MAG_FAMILIES
        and field == "CURRENT"
        and subfield in ("SP", "RB")
    ):
        return PARTITION_PYAT_COUPLED

    if (
        ring == "SR"
        and system == "DIAG"
        and family == "BPM"
        and field == "POSITION"
        and subfield in ("X", "Y")
    ):
        return PARTITION_PYAT_COUPLED

    if ring in ("BR", "BTS") and system == "MAG":
        return PARTITION_SP_ECHO

    if (
        ring == "SR"
        and system in ("RF", "VAC")
        and field in _SR_RF_VAC_SP_ECHO_FIELDS
        and subfield in ("SP", "RB")
    ):
        return PARTITION_SP_ECHO

    return PARTITION_STATIC_NOISY


def classify_partition(
    path: dict[str, str],
    grammar: ChannelGrammar | None = None,
    *,
    role: str = ROLE_NONE,
    counterpart_served: bool = False,
) -> str:
    """Classify one expanded channel's hierarchy path into a manifest partition.

    Args:
        path: Hierarchy path as produced by HierarchicalChannelDatabase,
            keyed by the levels the database declares.
        grammar: The database's channel grammar. ``None`` means the built-in
            grammar, for callers holding a reference-facility path alone.
        role: The channel's role in a declared pair (``ROLE_SETPOINT``,
            ``ROLE_READBACK`` or ``ROLE_NONE``), as ``grammar.role()``
            answered it.
        counterpart_served: Whether the other half of the channel's pair is
            in the namespace being served. A setpoint with nothing to echo
            into is not an echo pair.

    Returns:
        One of PARTITION_PYAT_COUPLED, PARTITION_SP_ECHO, PARTITION_STATIC_NOISY.
    """
    if grammar is None or grammar.is_builtin:
        return spec_partition(path)
    if role in (ROLE_SETPOINT, ROLE_READBACK) and counterpart_served:
        return PARTITION_SP_ECHO
    return PARTITION_STATIC_NOISY


# --- EPICS record type ---------------------------------------------------

RECORD_TYPE_BINARY = "bi"
RECORD_TYPE_ANALOG = "ai"
RECORD_TYPE_STRING = "stringin"
# The two remaining gateway channel shapes: a 512-byte char waveform ("long
# string", e.g. a status/message channel wider than stringin's 40 bytes) and
# a multi-bit binary (discrete enum state). `derive_record_type` never emits
# either -- the tutorial namespace has no such channel -- but a file-backed
# manifest (see loaders.load_manifest_file) may declare them, and
# ioc/records.py dispatches on them like any other record type.
RECORD_TYPE_LONG_STRING = "longstringin"
RECORD_TYPE_MBB = "mbbi"

# Tokens that indicate a two-state boolean signal rather than a continuous
# measurement: on the pairing level (the reference facility's ``subfield``)
# and on the level qualifying it (its ``field``).
_BOOLEAN_SUBFIELDS = frozenset(
    {
        "VALID",
        "FAULT",
        "READY",
        "ON",
        "INTERLOCK",
        "ALARM",
        "CONNECTED",
        "OPEN",
        "CLOSE",
        "CLOSED",
    }
)
_BOOLEAN_FIELDS = frozenset({"STATUS", "CONTROL"})


def derive_record_type(
    path: dict[str, str], grammar: ChannelGrammar | None = None
) -> tuple[str, bool]:
    """Derive an EPICS record type and noise flag from a channel's hierarchy path.

    Args:
        path: Hierarchy path as produced by HierarchicalChannelDatabase.
        grammar: The database's channel grammar, which names the level the
            signal token is read from and the level qualifying it. ``None``
            means the built-in grammar (``field`` and ``subfield``).

    Returns:
        (record_type, noise) where noise indicates whether the IOC should
        apply simulated measurement noise to this address:
          - booleans -> "bi", noise=False (a status flag doesn't jitter)
          - floats   -> "ai", noise=True (a measurement or setpoint readback does)
          - strings  -> "stringin", noise=False (reserved: the current
            namespace has no genuinely string-valued channel; kept for
            forward compatibility with future non-numeric DB additions)
    """
    if grammar is None:
        field, subfield = path["field"], path["subfield"]
    else:
        subfield = grammar.token(path)
        qualifier = grammar.qualifier_level
        field = path.get(qualifier, "") if qualifier is not None else ""

    if field in _BOOLEAN_FIELDS or subfield in _BOOLEAN_SUBFIELDS:
        return RECORD_TYPE_BINARY, False

    return RECORD_TYPE_ANALOG, True

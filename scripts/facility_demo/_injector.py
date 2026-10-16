"""The example facility's injector records, built from the element table.

``_elements.load_elements()`` reads ``injector_elements.tsv``; this module turns
the rows of the sections it emits into records and merges them into a facility
tree, the way ``_line.py`` merges the transfer line: a record already in a file
keeps its position, a new one is added, every other record keeps its text.

It emits the storage ring's two injection septa, SEK (``SR:MAG:SEPTUM:01``) and
SEN (``SR:MAG:SEPTUM:02``):

- a device of class ``Septum`` per septum, in the injection sector;
- each septum's current setpoint, readback and on-status, and on SEK the
  sampled current pulse, a 500-point waveform;
- the group ``SR/SEPTUM`` holding both;
- a seed per setpoint and on-status carrying the table's nominal, and on the
  SEK waveform a ``pulse`` driven by the SEK setpoint and enabled by its
  on-status.

The septa are fixed deck elements: no model wires them, the texture serves
every one of their channels from its seed. The readbacks' noise and the
setpoints' tolerances are the rule table's (``scripts/demo_seeds/rules.yaml``);
the tolerance written here is the role's, which the rule table restates.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import _elements
import _line

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo_seeds"))

import reseed

#: The sections whose rows this module emits.
SECTIONS = ("SR",)

#: The device classes this module emits within those sections.
CLASSES = ("Septum",)

#: Each septum's two-digit number, its name, and what it does.
SEPTA: dict[str, tuple[str, str]] = {
    "01": (
        "SEK",
        "pulsed injection septum; its current pulse is sampled as a waveform",
    ),
    "02": ("SEN", "the second injection septum; its current is read as a scalar"),
}

#: The place every septum sits in: the injection straight of sector 1.
PLACE = "SR/SECT1"

#: The group of the septa.
GROUP = "SR/SEPTUM"

#: What each septum channel's field and subfield read, for its description.
_FIELD_TEXT: dict[str, str] = {
    "CURRENT:SP": (
        "current setpoint (read-write): the commanded peak current of the septum pulse."
    ),
    "CURRENT:RB": "current readback (read-only): the measured peak current of the septum pulse.",
    "STATUS:ON": "on status (read-only): the septum supply is energized and pulsing.",
    "CURRENT:WAVEFORM": (
        "current pulse waveform (read-only): the sampled time trace of one current pulse, "
        "500 samples in A, refreshed about once a second. Its peak follows the current "
        "setpoint; it is flat zero while the septum is off."
    ),
}

#: What a channel adds to its description on a septum whose pulse is sampled.
_PULSE_TEXT: dict[str, str] = {
    "CURRENT:SP": " Scales the sampled current pulse.",
    "STATUS:ON": " When false the sampled current pulse is a flat zero trace.",
}


def _number(row: _elements.ElementRow) -> str:
    return row.demo_name.split(":")[3]


def _tail(row: _elements.ElementRow) -> str:
    return ":".join(row.demo_name.split(":")[4:])


def _device_id(row: _elements.ElementRow) -> str:
    return f"{row.section}/SEPTUM{_number(row)}"


def rows() -> list[_elements.ElementRow]:
    """The table's emitted rows, one per address, in table order.

    A channel bound by several legacy names has several rows; the first one
    stands for the channel.
    """
    seen: dict[str, _elements.ElementRow] = {}
    for row in _elements.load_elements():
        if row.section in SECTIONS and row.template.device_class in CLASSES:
            seen.setdefault(row.demo_name, row)
    return list(seen.values())


def devices() -> list[dict[str, Any]]:
    """The septa's devices, sorted by id."""
    out: dict[str, dict[str, Any]] = {}
    for row in rows():
        n = _number(row)
        name, role = SEPTA[n]
        out[_device_id(row)] = {
            "id": _device_id(row),
            "class": row.template.device_class,
            "description": f"Storage ring injection septum {name}: {role}.",
            "names": [f"SEPTUM{n}", name],
            "label": name,
            "place": PLACE,
        }
    return [out[key] for key in sorted(out)]


def _pulsed(number: str) -> bool:
    """Whether the septum numbered ``number`` has a sampled current pulse."""
    return any(_number(row) == number and row.template.value_type == "waveform" for row in rows())


def _description(row: _elements.ElementRow) -> str:
    name, _ = SEPTA[_number(row)]
    tail = _tail(row)
    extra = _PULSE_TEXT.get(tail, "") if _pulsed(_number(row)) else ""
    return f"Storage ring injection septum {name} {_FIELD_TEXT[tail]}{extra}"


def channels() -> list[dict[str, Any]]:
    """The septa's channels, sorted by address."""
    by_number = {(_number(row), row.template.site): row.demo_name for row in rows()}
    out: list[dict[str, Any]] = []
    for row in rows():
        template = row.template
        record: dict[str, Any] = {"id": row.demo_name}
        if template.writable:
            record["role"] = "setpoint"
            record["pair"] = by_number[(_number(row), "rb")]
            record["tolerance"] = {"absolute": template.tolerance}
        record["on"] = {"device": _device_id(row)}
        record["signal"] = template.signal
        if template.value_type != "float":
            record["value_type"] = template.value_type
        if template.shape is not None:
            record["shape"] = list(template.shape)
        if template.unit is not None:
            record["unit"] = template.unit
        record["description"] = _description(row)
        out.append(record)
    return sorted(out, key=lambda record: record["id"])


def groups() -> list[dict[str, Any]]:
    """The septa's group."""
    return [
        {
            "id": GROUP,
            "description": (
                "Injection Septa: the storage ring's two injection septum magnets, SEK and "
                "SEN, which bend the beam arriving from the booster-to-storage-ring line "
                "onto the ring's injection orbit while shielding the stored beam. SEK is "
                "pulsed, and its current pulse is sampled as a waveform."
            ),
            "names": ["injection septum"],
            "members": [device["id"] for device in devices()],
        }
    ]


def seeds() -> dict[str, dict[str, Any]]:
    """The septa's seed keys by address: a nominal, or the SEK waveform's pulse."""
    out: dict[str, dict[str, Any]] = {}
    sites = {(_number(row), row.template.site): row.demo_name for row in rows()}
    for row in rows():
        value = row.nominal_value()
        if row.template.value_type == "waveform":
            n = _number(row)
            out[row.demo_name] = {
                "pulse": {"driver": sites[(n, "sp")], "enable": sites[(n, "status")]}
            }
        elif value is not None and (row.template.writable or row.template.site == "status"):
            out[row.demo_name] = {"nominal": value}
    return out


# --- merging ----------------------------------------------------------------------

#: The seed keys this module owns; every other key of an entry is kept.
_SEED_KEYS = ("nominal", "pulse")


def _merge_seeds(path: Path, entries: dict[str, dict[str, Any]]) -> None:
    """Set the owned keys of each entry in ``seeds.yaml``, written as ``reseed`` writes it."""
    import yaml

    committed: dict[str, dict[str, Any]] = reseed.load(path) if path.is_file() else {}
    committed = dict(committed or {})
    for address, keys in entries.items():
        kept = {k: v for k, v in committed.get(address, {}).items() if k not in _SEED_KEYS}
        entry = {**kept, **keys}
        committed[address] = {key: entry[key] for key in reseed.KEY_ORDER if key in entry}
    document = {address: committed[address] for address in sorted(committed)}
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def write_sources(tree: Path) -> None:
    """Merge the emitted injector records into the facility tree ``tree``.

    Devices, channels and groups go into ``records/`` and the seed keys into
    ``seeds.yaml``; every other record keeps its text.
    """
    records = tree / "records"
    _line._merge(records / "devices.yaml", devices(), "id", ordered=True)
    _line._merge(records / "channels.yaml", channels(), "id", ordered=True)
    _line._merge(records / "groups.yaml", groups(), "id", ordered=True)
    _merge_seeds(tree / "seeds.yaml", seeds())

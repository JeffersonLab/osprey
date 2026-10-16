"""The example facility's injector records, merged from the element table.

The generator's ``injector`` mode merges the storage ring's injection septa SEK
and SEN into ``records/`` and ``seeds.yaml``. On a copy of the committed tree
with the septa removed it writes the committed records back, every other record
byte-equal; run twice on the committed tree it changes nothing. It writes no
limits: the demo ``limits.yaml`` holds only its teaching records. The septa
are texture rows: no model wires them, every setpoint and on-status carries a
seed, and the SEK current pulse is a ``pulse`` waveform driven by the SEK
setpoint and enabled by its on-status.
The rule table gives the septa their readback noise and setpoint tolerance, and
the committed seeds and channels are exactly what ``reseed`` writes.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from osprey.facility.sources import read_yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts/facility_demo/generate.py"
RESEED = REPO_ROOT / "scripts/demo_seeds/reseed.py"
EXAMPLE = REPO_ROOT / "src/osprey/templates/facilities/example"

SEK = "SR:MAG:SEPTUM:01"
SEN = "SR:MAG:SEPTUM:02"

#: The files the ``injector`` mode merges into, relative to the tree.
RECORDS = ["records/devices.yaml", "records/channels.yaml", "records/groups.yaml"]
MERGED = [*RECORDS, "seeds.yaml"]


def _is_septum(record_id: str) -> bool:
    return record_id.startswith(("SR:MAG:SEPTUM:", "SR/SEPTUM"))


def _chunks(text: str) -> list[str]:
    """A top-level YAML list's items, each as its exact text."""
    chunks: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.startswith("- ") or not chunks:
            chunks.append(line)
        else:
            chunks[-1] += line
    return chunks


def _chunk_id(chunk: str) -> str:
    (record,) = read_yaml(chunk)
    return str(record["id"])


def _without_septa(text: str) -> list[str]:
    return [chunk for chunk in _chunks(text) if not _is_septum(_chunk_id(chunk))]


def _run_injector(tree: Path) -> None:
    subprocess.run(
        [sys.executable, str(GENERATOR), "injector", str(tree)],
        check=True,
        capture_output=True,
    )


@cache
def _committed(rel: str) -> Any:
    return read_yaml((EXAMPLE / rel).read_text(encoding="utf-8"))


def _channels() -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in _committed("records/channels.yaml")}


def _devices() -> dict[str, dict[str, Any]]:
    return {record["id"]: record for record in _committed("records/devices.yaml")}


def _reseed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("reseed_under_test", RESEED)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stripped(tmp_path: Path) -> Path:
    """A copy of the committed example tree with the septa removed."""
    tree = tmp_path / "example"
    shutil.copytree(EXAMPLE, tree)
    for rel in RECORDS:
        path = tree / rel
        path.write_text("".join(_without_septa(path.read_text(encoding="utf-8"))), "utf-8")
    seeds = (tree / "seeds.yaml").read_text(encoding="utf-8")
    kept = [chunk for chunk in _top_level_keys(seeds) if not chunk.startswith("SR:MAG:SEPTUM:")]
    (tree / "seeds.yaml").write_text("".join(kept), "utf-8")
    return tree


def _top_level_keys(text: str) -> list[str]:
    """A top-level YAML mapping's entries, each as its exact text."""
    chunks: list[str] = []
    for line in text.splitlines(keepends=True):
        if not line.startswith(" ") or not chunks:
            chunks.append(line)
        else:
            chunks[-1] += line
    return chunks


# --- the generator -----------------------------------------------------------------


def test_the_injector_mode_writes_the_committed_records(stripped: Path) -> None:
    _run_injector(stripped)
    for rel in RECORDS:
        assert (stripped / rel).read_bytes() == (EXAMPLE / rel).read_bytes(), rel


def test_the_injector_mode_writes_the_committed_seed_keys(stripped: Path) -> None:
    _run_injector(stripped)
    written = read_yaml((stripped / "seeds.yaml").read_text(encoding="utf-8"))
    for address, seed in _committed("seeds.yaml").items():
        owned = {key: seed[key] for key in ("nominal", "pulse") if key in seed}
        if address.startswith("SR:MAG:SEPTUM:") and owned:
            assert written[address] == owned, address


def test_the_injector_mode_leaves_every_other_record_byte_equal(stripped: Path) -> None:
    before = {rel: (stripped / rel).read_text(encoding="utf-8") for rel in RECORDS}
    _run_injector(stripped)
    for rel in RECORDS:
        after = (stripped / rel).read_text(encoding="utf-8")
        assert _without_septa(after) == _chunks(before[rel]), rel


def test_the_injector_mode_leaves_the_limits_untouched(stripped: Path) -> None:
    before = (stripped / "limits.yaml").read_bytes()
    _run_injector(stripped)
    assert (stripped / "limits.yaml").read_bytes() == before


def test_the_injector_mode_is_idempotent(tmp_path: Path) -> None:
    tree = tmp_path / "example"
    shutil.copytree(EXAMPLE, tree)
    _run_injector(tree)
    _run_injector(tree)
    for rel in [*MERGED, "limits.yaml"]:
        assert (tree / rel).read_bytes() == (EXAMPLE / rel).read_bytes(), rel


# --- the records -------------------------------------------------------------------


def test_the_septa_are_septum_devices_in_the_storage_ring() -> None:
    devices = {key: value for key, value in _devices().items() if _is_septum(key)}
    assert sorted(devices) == ["SR/SEPTUM01", "SR/SEPTUM02"]
    assert {device["class"] for device in devices.values()} == {"Septum"}
    assert devices["SR/SEPTUM01"]["label"] == "SEK"
    assert devices["SR/SEPTUM02"]["label"] == "SEN"
    for device in devices.values():
        assert device["place"].split("/")[0] == "SR"
        assert device["description"]


def test_each_septum_has_its_setpoint_readback_and_on_status() -> None:
    channels = _channels()
    for prefix, device in ((SEK, "SR/SEPTUM01"), (SEN, "SR/SEPTUM02")):
        sp, rb, on = (
            channels[f"{prefix}:{tail}"] for tail in ("CURRENT:SP", "CURRENT:RB", "STATUS:ON")
        )
        assert sp["role"] == "setpoint"
        assert sp["pair"] == rb["id"]
        assert sp["signal"] == "current_setpoint" and sp["unit"] == "A"
        assert rb["signal"] == "current_readback" and rb["unit"] == "A"
        assert on["signal"] == "power_on_status" and on["value_type"] == "bool"
        for channel in (sp, rb, on):
            assert channel["on"] == {"device": device}


def test_only_sek_carries_the_sampled_current_pulse() -> None:
    waveforms = {
        address: channel
        for address, channel in _channels().items()
        if address.startswith("SR:MAG:SEPTUM:") and channel.get("value_type") == "waveform"
    }
    assert list(waveforms) == [f"{SEK}:CURRENT:WAVEFORM"]
    (channel,) = waveforms.values()
    assert channel["shape"] == [500]
    assert channel["signal"] == "pulse_waveform"
    assert channel["unit"] == "A"
    assert "role" not in channel


def test_every_septum_channel_has_a_description() -> None:
    for address, channel in _channels().items():
        if address.startswith("SR:MAG:SEPTUM:"):
            assert channel.get("description"), address
    assert "SEK" in _channels()[f"{SEK}:CURRENT:SP"]["description"]
    assert "SEN" in _channels()[f"{SEN}:CURRENT:SP"]["description"]
    for tail in ("CURRENT:SP", "STATUS:ON"):
        assert "sampled current pulse" in _channels()[f"{SEK}:{tail}"]["description"]
        assert "sampled current pulse" not in _channels()[f"{SEN}:{tail}"]["description"]


def test_no_model_wires_a_septum() -> None:
    for model in _committed("models.yaml"):
        for record in model.get("wiring", []):
            assert not str(record["address"]).startswith("SR:MAG:SEPTUM:"), model["name"]


# --- the seeds ---------------------------------------------------------------------


def test_every_septum_setpoint_and_on_status_carries_its_nominal() -> None:
    seeds = _committed("seeds.yaml")
    assert seeds[f"{SEK}:CURRENT:SP"]["nominal"] == 3000.0
    assert seeds[f"{SEN}:CURRENT:SP"]["nominal"] == 800.0
    assert seeds[f"{SEK}:STATUS:ON"]["nominal"] == "TRUE"
    assert seeds[f"{SEN}:STATUS:ON"]["nominal"] == "TRUE"


def test_the_sek_waveform_pulses_from_its_setpoint_and_on_status() -> None:
    seeds = _committed("seeds.yaml")
    assert seeds[f"{SEK}:CURRENT:WAVEFORM"] == {
        "pulse": {"driver": f"{SEK}:CURRENT:SP", "enable": f"{SEK}:STATUS:ON"}
    }


def test_no_storage_ring_channel_carries_a_gate() -> None:
    gated = [
        address
        for address, seed in _committed("seeds.yaml").items()
        if address.startswith("SR:") and "gate" in seed
    ]
    assert gated == []


def test_the_seeds_and_channels_are_what_reseed_writes() -> None:
    reseed = _reseed()
    assert (EXAMPLE / "seeds.yaml").read_text(encoding="utf-8") == reseed.render()
    assert (EXAMPLE / "records/channels.yaml").read_text(encoding="utf-8") == reseed.stamp()


def test_every_septum_setpoint_carries_its_rule_tolerance() -> None:
    reseed = _reseed()
    tolerances = reseed.tolerances()
    for prefix in (SEK, SEN):
        address = f"{prefix}:CURRENT:SP"
        assert _channels()[address]["tolerance"] == {"absolute": tolerances[address]}
        assert tolerances[address] == 1.0


def test_every_septum_rule_row_names_a_source() -> None:
    rows = [row for row in _reseed().load_rules() if row["class"] == "Septum"]
    assert {row["signal"] for row in rows} == {"current_setpoint", "current_readback"}
    assert all(row["source"] for row in rows)


def test_each_septum_readback_moves_by_its_rule_noise() -> None:
    seeds = _committed("seeds.yaml")
    for prefix in (SEK, SEN):
        assert seeds[f"{prefix}:CURRENT:RB"]["noise"] == {"absolute": 0.1}


# --- the limits and the group ------------------------------------------------------


def test_no_septum_channel_has_a_limits_record() -> None:
    addresses = [record["address"] for record in _committed("limits.yaml")["records"]]
    assert [address for address in addresses if address.startswith((SEK, SEN))] == []


def test_the_septum_group_lists_sek_and_sen() -> None:
    groups = {record["id"]: record for record in _committed("records/groups.yaml")}
    group = groups["SR/SEPTUM"]
    assert group["members"] == ["SR/SEPTUM01", "SR/SEPTUM02"]
    assert "SEK" in group["description"] and "SEN" in group["description"]


def test_the_middle_layer_view_keys_both_septa_under_the_septum_family() -> None:
    from osprey.facility.views.channel_finder import middle_layer_families

    doc = {
        "devices": _committed("records/devices.yaml"),
        "groups": _committed("records/groups.yaml"),
    }
    assert middle_layer_families(doc)["Septum"] == [("SR", "SEPTUM")]


# --- the build ---------------------------------------------------------------------


def test_the_example_tree_validates() -> None:
    from osprey.facility.validate import validate

    out = io.StringIO()
    assert validate(EXAMPLE, project_name="example", file=out) == 0, out.getvalue()
    assert "seed-missing" not in out.getvalue()
    assert "seed-invalid" not in out.getvalue()

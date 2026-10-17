"""Facility-added device classes through ``osprey build``.

``classes.yaml`` declares classes beyond the vocabulary, each under a vocabulary
class or an earlier declared one. A device may carry a declared class, and
``facility.json`` ``classes`` holds ``classes.yaml``'s records verbatim, sorted
by class. A class that is declared nowhere stops the build with one
``class-unknown`` line.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from click.testing import Result

from tests.facility._synthetic_trees import plain_tree

if TYPE_CHECKING:
    from tests.facility.conftest import BuiltProject

Build = Callable[..., tuple["BuiltProject", Result]]

VOCABULARY_JSON = (
    Path(__file__).resolve().parents[2] / "src/osprey/facility/schema/_generated/vocabulary.json"
)

KICKER = {
    "class": "Kicker",
    "parent": "Magnet",
    "aliases": ["kicker magnet"],
    "description": "A fast pulsed dipole.",
}
FAST_KICKER = {"class": "FastKicker", "parent": "Kicker"}


def _tree(classes: list[dict[str, Any]] | None, device_class: str) -> dict[str, Any]:
    tree = plain_tree()
    tree["records/devices.yaml"].append({"id": "SR/K1", "class": device_class})
    if classes is not None:
        tree["classes.yaml"] = classes
    return tree


def test_a_declared_child_class_builds_and_is_carried_verbatim(build_project: Build) -> None:
    project, result = build_project(_tree([KICKER, FAST_KICKER], "FastKicker"))

    assert result.exit_code == 0, result.output
    assert project.facility["classes"] == [FAST_KICKER, KICKER]
    [kicker] = [d for d in project.facility["devices"] if d["id"] == "SR/K1"]
    assert kicker["class"] == "FastKicker"


def test_a_tree_without_classes_yaml_carries_no_classes(build_project: Build) -> None:
    project, result = build_project(_tree(None, "Quadrupole"))

    assert result.exit_code == 0, result.output
    assert project.facility["classes"] == []


def test_an_undeclared_device_class_stops_the_build(build_project: Build) -> None:
    _project, result = build_project(_tree(None, "Kicker"))

    assert result.exit_code == 1
    assert result.stderr == (
        "facility: class-unknown: device SR/K1 — class Kicker is in neither the vocabulary "
        "nor classes.yaml; fix: use a vocabulary class or add it to classes.yaml\n"
    )


def test_an_undeclared_parent_stops_the_build(build_project: Build) -> None:
    _project, result = build_project(_tree([FAST_KICKER], "FastKicker"))

    assert result.exit_code == 1
    assert result.stderr == (
        "facility: class-unknown: class FastKicker — classes.yaml `parent` Kicker is neither "
        "a vocabulary class nor an earlier facility-added class; fix: name a vocabulary class "
        "or a class listed earlier in classes.yaml\n"
    )


def test_septum_is_a_vocabulary_class_and_builds_without_classes_yaml(
    build_project: Build,
) -> None:
    project, result = build_project(_tree(None, "Septum"))

    assert result.exit_code == 0, result.output
    assert project.facility["classes"] == []
    [septum] = [d for d in project.facility["devices"] if d["id"] == "SR/K1"]
    assert septum["class"] == "Septum"


def test_a_facility_class_may_extend_the_septum(build_project: Build) -> None:
    lambertson = {"class": "LambertsonSeptum", "parent": "Septum"}
    project, result = build_project(_tree([lambertson], "LambertsonSeptum"))

    assert result.exit_code == 0, result.output
    assert project.facility["classes"] == [lambertson]


def test_the_vocabulary_declares_septum_and_the_pulse_waveform_role() -> None:
    vocabulary = json.loads(VOCABULARY_JSON.read_text(encoding="utf-8"))
    classes = {record["name"]: record for record in vocabulary["classes"]}
    roles = {record["name"]: record for record in vocabulary["signal_roles"]}

    assert classes["Septum"]["parent"] == "Magnet"
    assert classes["Septum"]["abstract"] is False
    assert classes["Septum"]["description"]
    assert roles["pulse_waveform"]["description"]

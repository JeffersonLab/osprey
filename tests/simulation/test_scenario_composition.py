"""Composition contract: disjoint scenarios stack; overlapping ones are rejected.

Two simultaneously active scenarios must touch disjoint channel sets — archiver
step/ramp events overwrite the synthesized series (and overrides collide on
point reads), so overlapping scenarios would compose order-dependently and
silently wrong. These tests pin both halves: (1) disjoint scenarios on a
hand-built machine compose and yield *both* signatures at once, and
(2) overlapping scenarios are rejected — on a hand-built same-channel collision
and on the shipped pair vacuum-burst + rf-thermal, which both script the beam
current. Each shipped fault scenario composes cleanly with ``nominal``.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from osprey.simulation import SimulationEngine

DCCT = "SR:DIAG:DCCT:01:CURRENT:RB"


def _window(n: int = 100) -> list[datetime]:
    """A one-hour window ending now; ``at`` fractions place events inside it."""
    now = datetime.now(UTC)
    step = timedelta(hours=1) / n
    return [now - timedelta(hours=1) + step * i for i in range(n)]


class TestDisjointComposition:
    """A hand-built machine where two scenarios touch different channels."""

    DISJOINT = {
        "name": "compose",
        "channels": {"A": {"value": 1.0}, "B": {"value": 2.0}},
        "scenarios": {
            "nominal": {"description": "n"},
            "fault-a": {
                "description": "a",
                "archiver": [{"channel": "A", "events": [{"shape": "step", "at": 0.5, "to": 7.0}]}],
            },
            "fault-b": {
                "description": "b",
                "archiver": [{"channel": "B", "events": [{"shape": "step", "at": 0.5, "to": 9.0}]}],
            },
        },
    }

    def _engine(self, make_machine_file) -> SimulationEngine:
        return SimulationEngine.from_file(make_machine_file(self.DISJOINT))

    @staticmethod
    def _stepped(engine: SimulationEngine, pv: str, to: float) -> bool:
        return float(np.array(engine.synthesize_series(pv, _window()))[-1]) == to

    def test_nominal_alone_shows_neither_fault(self, make_machine_file):
        engine = self._engine(make_machine_file)
        engine.set_active_scenarios(["nominal"])
        assert not self._stepped(engine, "A", 7.0)
        assert not self._stepped(engine, "B", 9.0)

    def test_composed_pair_shows_both_faults(self, make_machine_file):
        engine = self._engine(make_machine_file)
        assert engine.validate_composition(["nominal", "fault-a", "fault-b"]) == []
        engine.set_active_scenarios(["fault-a", "fault-b"])
        assert engine.active_scenarios() == ("nominal", "fault-a", "fault-b")
        # Both overlays are live at once on their disjoint channels.
        assert self._stepped(engine, "A", 7.0), "fault-a signature missing under composition"
        assert self._stepped(engine, "B", 9.0), "fault-b signature missing under composition"


class TestShippedScenarios:
    """The shipped fault scenarios each compose with nominal, not with each other."""

    def test_each_fault_composes_with_nominal(self, engine_factory):
        engine = engine_factory("nominal")
        assert engine.validate_composition(["nominal", "rf-thermal"]) == []
        assert engine.validate_composition(["nominal", "vacuum-burst"]) == []

    def test_vacuum_burst_and_rf_thermal_collide_on_the_beam_current(self, engine_factory):
        engine = engine_factory("nominal")
        problems = engine.validate_composition(["vacuum-burst", "rf-thermal"])
        assert len(problems) == 1
        assert repr(DCCT) in problems[0]
        assert "vacuum-burst" in problems[0] and "rf-thermal" in problems[0]

    def test_set_active_scenarios_refuses_the_pair(self, engine_factory):
        engine = engine_factory("nominal")
        with pytest.raises(ValueError, match="disjoint channel sets"):
            engine.set_active_scenarios(["vacuum-burst", "rf-thermal"])


class TestCollisionRejected:
    """A hand-built machine where two scenarios touch one channel must be rejected."""

    COLLIDING = {
        "name": "collide",
        "channels": {"C": {"value": 1.0}, "D": {"value": 2.0}},
        "scenarios": {
            "nominal": {"description": "n"},
            "over-a": {"description": "a", "overrides": {"C": 5.0}},
            "over-b": {"description": "b", "overrides": {"C": 9.0}},
            "arch-c": {
                "description": "c",
                "archiver": [{"channel": "C", "events": [{"shape": "step", "at": 0.5, "to": 7.0}]}],
            },
            "disjoint-d": {"description": "d", "overrides": {"D": 3.0}},
        },
    }

    def _engine(self, make_machine_file) -> SimulationEngine:
        return SimulationEngine.from_file(make_machine_file(self.COLLIDING))

    def test_two_overrides_on_one_channel_collide(self, make_machine_file):
        engine = self._engine(make_machine_file)
        problems = engine.validate_composition(["over-a", "over-b"])
        assert len(problems) == 1
        assert "'C'" in problems[0]
        assert "over-a" in problems[0] and "over-b" in problems[0]

    def test_override_and_archiver_on_one_channel_collide(self, make_machine_file):
        engine = self._engine(make_machine_file)
        assert engine.validate_composition(["over-a", "arch-c"]) != []

    def test_disjoint_scenarios_do_not_collide(self, make_machine_file):
        engine = self._engine(make_machine_file)
        assert engine.validate_composition(["over-a", "disjoint-d"]) == []

    def test_set_active_scenarios_raises_on_collision(self, make_machine_file):
        engine = self._engine(make_machine_file)
        with pytest.raises(ValueError, match="disjoint channel sets"):
            engine.set_active_scenarios(["over-a", "over-b"])

    def test_unknown_scenario_reported(self, make_machine_file):
        engine = self._engine(make_machine_file)
        problems = engine.validate_composition(["no-such-scenario"])
        assert len(problems) == 1
        assert "Unknown scenario" in problems[0]

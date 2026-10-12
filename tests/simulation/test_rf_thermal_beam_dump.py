"""The rf-thermal scenario's trip night is a beam dump in the beam-current data.

The scenario narrates one: the logbook's DEMO-026 records CAVITY01's
reflected-power interlock tripping at 03:15 and the beam restored at 04:30, and
the RF channels show forward power at zero for that stretch. The stored beam
current has to tell the same story. A storage ring that loses its RF loses its
beam within a turn or two, so a DCCT that stays at 500 mA through 75 minutes of
RF-off is not a quiet channel — it is data that contradicts the prompt
("the beam dumped") and the logbook. An agent that reads it and says so is right
to, and the scenario's judge then had no honest way to tell a careful diagnosis
from a hedge.

Pinned on ``synthesize_series`` over the trip night, which is where the agent's
archiver read lands: beam present before the trip, absent between trip and
refill, present again after.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import numpy as np

from osprey.utils.config import get_facility_timezone

DCCT = "SR:DIAG:DCCT:01:CURRENT:RB"
NOMINAL_MA = 500.0
TRIP_DAYS_AGO = 4  # DEMO-026's `when`, and the trip-day `at_when` in scenario.json
TRIP = time(3, 15)  # reflected-power interlock
REFILL = time(4, 30)  # "beam restored at 04:30"


def _trip_night(step: timedelta = timedelta(minutes=1)) -> list[datetime]:
    """Per-minute timestamps over 02:30–05:30 on the trip day, facility-local.

    The engine resolves ``at_when`` against the apply-time anchor's calendar day
    in the facility zone, and the fixture anchors within a second of now, so the
    trip day is simply four days before today in that zone.
    """
    zone = get_facility_timezone()
    day = (datetime.now(zone) - timedelta(days=TRIP_DAYS_AGO)).date()
    start = datetime.combine(day, time(2, 30), zone)
    return [start + step * i for i in range(3 * 60)]


def _at(stamps: list[datetime], series: np.ndarray, clock: time) -> float:
    index = next(i for i, stamp in enumerate(stamps) if stamp.time() >= clock)
    return float(series[index])


def test_the_beam_is_gone_between_the_trip_and_the_refill(engine_factory) -> None:
    engine = engine_factory("rf-thermal")
    stamps = _trip_night()
    current = np.array(engine.synthesize_series(DCCT, stamps))

    # Beam stored before the trip ...
    assert abs(_at(stamps, current, time(3, 0)) - NOMINAL_MA) < 5.0
    # ... dumped once the interlock trips ...
    assert _at(stamps, current, time(3, 20)) < 5.0
    assert _at(stamps, current, time(4, 0)) < 5.0
    assert _at(stamps, current, time(4, 25)) < 5.0
    # ... and restored at the refill the logbook records.
    assert abs(_at(stamps, current, time(4, 40)) - NOMINAL_MA) < 5.0
    assert abs(_at(stamps, current, time(5, 20)) - NOMINAL_MA) < 5.0


def test_the_dump_spans_the_rf_off_stretch_the_logbook_narrates(engine_factory) -> None:
    """Trip at 03:15, restored at 04:30 — the same clock the narrative gives."""
    engine = engine_factory("rf-thermal")
    stamps = _trip_night()
    current = np.array(engine.synthesize_series(DCCT, stamps))

    beam_absent = current < 5.0
    first_absent = stamps[int(np.argmax(beam_absent))]
    last_absent = stamps[len(stamps) - 1 - int(np.argmax(beam_absent[::-1]))]

    assert beam_absent.any(), "the trip night never loses the beam"
    assert (
        abs(
            (
                first_absent - datetime.combine(first_absent.date(), TRIP, first_absent.tzinfo)
            ).total_seconds()
        )
        <= 120
    )
    assert (
        abs(
            (
                last_absent - datetime.combine(last_absent.date(), REFILL, last_absent.tzinfo)
            ).total_seconds()
        )
        <= 120
    )


def test_a_quiet_night_keeps_the_beam(engine_factory) -> None:
    """The dump is the trip night's, not every night's: five days back is calm."""
    engine = engine_factory("rf-thermal")
    zone = get_facility_timezone()
    day = (datetime.now(zone) - timedelta(days=TRIP_DAYS_AGO + 1)).date()
    start = datetime.combine(day, time(2, 30), zone)
    stamps = [start + timedelta(minutes=i) for i in range(3 * 60)]
    current = np.array(engine.synthesize_series(DCCT, stamps))

    assert np.all(np.abs(current - NOMINAL_MA) < 5.0)

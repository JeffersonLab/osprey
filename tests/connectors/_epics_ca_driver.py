"""Child-process driver: the EPICS connector against a live soft IOC.

Run by ``test_epics_ca_softioc.py`` as ``python _epics_ca_driver.py <scenario>
<prefix>``, with ``EPICS_CA_*`` pointing at the test's IOC. Prints one line,
``__RESULT__<json>``, and exits; the exit code is part of what is tested,
because a crash in Channel Access teardown only shows there. Underscore-
prefixed, so pytest never collects it.

Each scenario runs in a process of its own: the connector's CA loop claims the
process's Channel Access environment on first use, so no two IOCs, and no test
of what happens at exit, can share one.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
import threading
from typing import Any
from unittest.mock import patch

from osprey_connectors.control_system.epics_connector import EPICSConnector

RESULT_MARKER = "__RESULT__"


def _metadata(value: Any) -> dict[str, Any]:
    meta = value.metadata
    plain = value.value.tolist() if hasattr(value.value, "tolist") else value.value
    return {
        "value": plain,
        "type": type(value.value).__name__,
        "units": meta.units,
        "precision": meta.precision,
        "alarm_status": meta.alarm_status,
        "alarm_severity": meta.alarm_severity,
        "enum_label": meta.enum_label,
        "enum_labels": meta.enum_labels,
    }


def _write(result: Any) -> dict[str, Any]:
    return {
        "outcome": result.outcome.name,
        "observed": result.observed_value,
        "alarm_status": result.alarm_status,
        "refusal_reason": result.refusal_reason,
        "error": result.error_message,
    }


async def _connect() -> EPICSConnector:
    connector = EPICSConnector()
    await connector.connect({"timeout_s": 2})
    return connector


async def contract(prefix: str) -> dict[str, Any]:
    """Every read shape and every write outcome, over the wire."""
    out: dict[str, Any] = {"reads": {}, "writes": {}}
    connector = await _connect()
    for record in ("AO", "LONG", "MBBO", "STR"):
        out["reads"][record] = _metadata(await connector.read_channel(f"{prefix}:{record}"))
    try:
        await connector.read_channel(f"{prefix}:NOPE", timeout=0.5)
    except Exception as exc:  # the exception class is the assertion
        out["reads"]["NOPE"] = type(exc).__name__

    cases = {
        "confirmed": (f"{prefix}:AO", 2.25, {}),
        "into_alarm": (f"{prefix}:AO", 9.0, {}),
        "enum_label": (f"{prefix}:MBBO", "Off", {}),
        "unrequested": (f"{prefix}:AO", 3.0, {"confirm": False}),
        "not_sent": (f"{prefix}:NOPE", 1.0, {"timeout": 0.5}),
        "unacknowledged": (f"{prefix}:SLOW", 1.0, {"timeout": 1.0}),
        "access_denied": (f"{prefix}:RO", 5.0, {}),
    }
    for name, (address, value, kwargs) in cases.items():
        out["writes"][name] = _write(await connector.write_channel(address, value, **kwargs))

    updates: list[float] = []
    sub_id = await connector.subscribe(f"{prefix}:AO", lambda v: updates.append(v.value))
    await asyncio.sleep(0.5)
    await connector.write_channel(f"{prefix}:AO", 4.5)
    await asyncio.sleep(0.5)
    await connector.unsubscribe(sub_id)
    await connector.write_channel(f"{prefix}:AO", 5.5)
    await asyncio.sleep(0.5)
    out["monitor"] = updates

    read_current = connector._current_value_reader()
    out["max_step"] = [
        await asyncio.to_thread(read_current, f"{prefix}:AO"),
        await asyncio.to_thread(read_current, f"{prefix}:NOPE"),
    ]
    return out


def runtime_style(prefix: str) -> dict[str, Any]:
    """Reads the way ``osprey.runtime`` makes them: a fresh loop (and thread) per call."""
    from aioca._catools import _Context

    connector = asyncio.run(_connect())
    values = [asyncio.run(connector.read_channel(f"{prefix}:AO")).value for _ in range(10)]

    def in_a_thread() -> None:
        values.append(asyncio.run(connector.read_channel(f"{prefix}:AO")).value)

    for _ in range(10):
        worker = threading.Thread(target=in_a_thread)
        worker.start()
        worker.join()
    return {"reads": len(values), "channel_caches": len(_Context._channel_caches)}


async def aioca_first(prefix: str) -> dict[str, Any]:
    """aioca used directly on this thread before the connector: one context, clean exit."""
    import aioca

    direct = float(await aioca.caget(f"{prefix}:AO", timeout=2))
    connector = await _connect()
    read = await connector.read_channel(f"{prefix}:AO")
    write = await connector.write_channel(f"{prefix}:AO", 2.0)
    await connector.subscribe(f"{prefix}:AO", lambda _value: None)
    return {"direct": direct, "read": read.value, "write": write.outcome.name}


async def connector_first(prefix: str) -> dict[str, Any]:
    import aioca

    connector = await _connect()
    write = await connector.write_channel(f"{prefix}:AO", 3.0)
    await connector.subscribe(f"{prefix}:AO", lambda _value: None)
    direct = float(await aioca.caget(f"{prefix}:AO", timeout=2))
    return {"direct": direct, "write": write.outcome.name}


async def dispatch(prefix: str) -> dict[str, Any]:
    """The dispatch trigger source and the connector, on one CA loop."""
    import types

    from osprey.dispatch.sources.epics_ca import EpicsCaSource

    fired: list[list[float]] = []

    async def fire(_trigger: Any, payload: dict[str, Any]) -> None:
        fired.append([payload["previous_value"], payload["value"]])

    trigger = types.SimpleNamespace(
        name="crossing",
        source_config={"pv": f"{prefix}:AO", "threshold": 5.0, "cool_down_sec": 0},
    )
    source = EpicsCaSource()
    await source.start([trigger], fire)
    connector = await _connect()
    await asyncio.sleep(0.5)
    for value in (1.0, 6.0, 2.0, 7.5):
        await connector.write_channel(f"{prefix}:AO", value)
        await asyncio.sleep(0.3)
    await source.stop()
    return {"fired": fired}


SCENARIOS = {
    "contract": contract,
    "runtime_style": runtime_style,
    "aioca_first": aioca_first,
    "connector_first": connector_first,
    "dispatch": dispatch,
}


def main() -> None:
    scenario, prefix = sys.argv[1], sys.argv[2]
    run = SCENARIOS[scenario]
    with patch.object(EPICSConnector, "_writes_enabled", property(lambda _self: True)):
        result = asyncio.run(run(prefix)) if inspect.iscoroutinefunction(run) else run(prefix)
    print(RESULT_MARKER + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()

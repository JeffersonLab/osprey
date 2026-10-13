"""The server half of the live Channel Access suites, run in a process of its own.

``tests/va/test_record_factory.py`` and ``tests/va/test_apply_fault.py`` drive a
real ``pcaspy`` server with a real ``aioca`` client. The two cannot share a
process: pcaspy's extension statically bundles its own EPICS base, and loaded
after aioca has put epicscorelibs' libca and libCom in the global symbol scope
it binds its EPICS symbols to those copies and drops the client's circuit on
every write. So the client stays in the pytest process and the server lives
here, in a ``spawn`` child that never imports aioca or the connector's Channel
Access code -- :func:`_assert_no_ca_client` checks that at startup and again
with the server up, and the child fails loudly if it is ever violated.

The server is described by a plain, picklable *spec* (the served channels, the
drive limits, the boot values, the stuck setpoints and what the stand-in
physics hook does), so this module knows nothing about either suite. The parent
holds a :class:`LiveServer`, which mirrors the attribute shape the suites read:
``live.hook.calls`` and ``live.hook.threads`` (each a fresh copy fetched from
the child, whose ``clear()`` clears the child's too), ``live.loop.thread.name``
and ``live.refusal_alarm``.

Nothing here imports anything beyond the standard library at module scope, so
importing this module in the spawned child costs nothing and loads nothing the
child must not have.
"""

from __future__ import annotations

import multiprocessing
import sys
import threading
import traceback
from queue import Queue
from types import SimpleNamespace
from typing import Any

#: Modules whose presence in the server process would mean aioca's libca is
#: (or is about to be) loaded alongside pcaspy's bundled EPICS base.
_CLIENT_MODULES = ("aioca", "epicscorelibs.ca.cadef", "osprey_connectors.control_system")

#: How long the parent waits for the child to come up, and to go away.
START_TIMEOUT_S = 60.0
STOP_TIMEOUT_S = 10.0
REQUEST_TIMEOUT_S = 10.0


class ServerUnavailable(RuntimeError):
    """The child could not import pcaspy: the venue has no Channel Access server."""


# --------------------------------------------------------------------------
# Child side
# --------------------------------------------------------------------------


class RunLoop:
    """The one property of the real run loop the write path depends on.

    A queued write is applied and completed from a thread that is never the
    Channel Access server's, because the model underneath is not thread-safe.
    Everything else the real loop does -- batching, the output pass, the
    rollback -- is either disabled by the runner's configuration policy or
    irrelevant to what a client observes, and is proven in process elsewhere.
    """

    def __init__(self, on_setpoint, *, name: str = "va-test-run-loop") -> None:
        self._on_setpoint = on_setpoint
        self._queue: Queue = Queue()
        self.thread = threading.Thread(target=self._run, daemon=True, name=name)
        self.thread.start()

    def enqueue(self, values: dict, *, done) -> None:  # test-local callable
        self._queue.put((values, done))

    def _run(self) -> None:
        while True:
            values, done = self._queue.get()
            error = None
            try:
                for address, item in values.items():
                    self._on_setpoint(address, item["value"])
            except Exception as exc:  # the loop reports, never raises
                error = str(exc)
            done(error)


class PhysicsHook:
    """Stands in for the physics bridge: records a write, then pushes a reading.

    Faithful on the points a client can see. It runs on the loop's thread; it
    refuses by raising, as the model does, when handed ``refused_value``; and
    the reading it pushes onto ``bpm`` is its own -- never a value read back
    out of whatever took the write -- so a reading on the wire can only have
    come from here. With no ``records`` it only records.
    """

    def __init__(
        self,
        records: Any = None,
        *,
        bpm: str | None = None,
        bpm_reading: float = 0.0,
        refused_value: float | None = None,
        refusal_reason: str = "refused",
    ) -> None:
        self._records = records
        self._bpm = bpm
        self._bpm_reading = bpm_reading
        self._refused_value = refused_value
        self._refusal_reason = refusal_reason
        self._lock = threading.Lock()
        self.calls: list[tuple[str, float]] = []
        self.threads: set[str] = set()

    def __call__(self, address: str, value: float) -> None:
        with self._lock:
            self.threads.add(threading.current_thread().name)
        if self._refused_value is not None and value == self._refused_value:
            raise ValueError(self._refusal_reason)
        with self._lock:
            self.calls.append((address, value))
        if self._records is not None and self._bpm is not None:
            self._records.all[self._bpm].set(self._bpm_reading)

    def snapshot(self, what: str) -> Any:
        with self._lock:
            return list(self.calls) if what == "calls" else set(self.threads)

    def clear(self, what: str) -> None:
        with self._lock:
            (self.calls if what == "calls" else self.threads).clear()


def _assert_no_ca_client(when: str) -> None:
    """Fail loudly if this process has loaded the Channel Access client."""
    loaded = [name for name in _CLIENT_MODULES if name in sys.modules]
    if loaded:
        raise AssertionError(
            f"the live CA server process loaded {loaded} {when}; pcaspy must never "
            "share a process with aioca's libca (see tests/va/_live_ca_server.py)"
        )


def _serve(spec: dict) -> tuple[Any, PhysicsHook, RunLoop, Any, threading.Event, Any]:
    """Assemble the serving layer exactly as the entrypoint assembles it.

    Database first, with every boot value already in it, because the Channel
    Access server copies each spec when it creates the PV; the driver, and so
    the records' attachment to it, only after the server exists.
    """
    import pcaspy

    from osprey.services.virtual_accelerator.serving.pvdb import build_serving_pvdb
    from osprey.services.virtual_accelerator.serving.write_path import (
        CohostWritePath,
        physics_setpoint_addresses,
    )

    drive_limits = {address: tuple(band) for address, band in spec["drive_limits"].items()}
    records = build_serving_pvdb(
        spec["channels"],
        drive_limits=drive_limits or None,
        boot_values=spec["boot_values"],
        async_setpoints=True,
    )
    hook = PhysicsHook(
        records,
        bpm=spec.get("bpm"),
        bpm_reading=spec.get("bpm_reading", 0.0),
        refused_value=spec.get("refused_value"),
        refusal_reason=spec.get("refusal_reason", "refused"),
    )
    loop = RunLoop(hook, name=f"{spec['name']}-run-loop")
    refusal_alarm = (pcaspy.Alarm.WRITE_ALARM, pcaspy.Severity.INVALID_ALARM)
    path = CohostWritePath(
        records,
        enqueue=loop.enqueue,
        physics_setpoints=physics_setpoint_addresses(records),
        stuck_setpoints=frozenset(spec["stuck_setpoints"]),
        drive_limits=drive_limits or None,
        refusal_alarm=refusal_alarm,
    )

    class LiveDriver(pcaspy.Driver):
        """The production driver's whole body: delegate to the write path."""

        def write(self, reason: str, value: Any) -> bool:  # pcaspy contract
            accepted: bool = path.write(self, reason, value)
            return accepted

    server = pcaspy.SimpleServer()
    server.createPV("", records.pvdb)
    driver = LiveDriver()
    records.attach_driver(driver)

    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            server.process(0.05)

    thread = threading.Thread(target=serve, daemon=True, name=f"{spec['name']}-cas")
    thread.start()
    # Returned so every object stays referenced for the child's lifetime.
    return server, hook, loop, refusal_alarm, stop, (thread, driver, path)


def _child_main(conn: Any, spec: dict) -> None:
    """Entry point of the spawned server process."""
    import os

    os.environ.update(spec["env"])
    try:
        _assert_no_ca_client("at startup")
        try:
            server, hook, loop, refusal_alarm, stop, keep = _serve(spec)
        except ImportError as exc:
            if getattr(exc, "name", None) == "pcaspy" or "pcaspy" in str(exc):
                conn.send(("unavailable", f"pcaspy is not importable: {exc}"))
                return
            raise
        _assert_no_ca_client("with the server up")
    except BaseException:
        conn.send(("error", traceback.format_exc()))
        raise

    conn.send(
        (
            "ready",
            {
                "loop_thread": loop.thread.name,
                "refusal_alarm": tuple(int(v) for v in refusal_alarm),
            },
        )
    )
    try:
        while True:
            try:
                request = conn.recv()
            except EOFError:  # the parent went away
                break
            op, what = request
            if op == "stop":
                break
            if op == "get":
                conn.send(hook.snapshot(what))
            elif op == "clear":
                hook.clear(what)
                conn.send(None)
    finally:
        stop.set()
        keep[0].join(timeout=5)
        del server
    conn.send(("stopped", None))


# --------------------------------------------------------------------------
# Parent side
# --------------------------------------------------------------------------


class _RemoteList(list):
    """A copy of the child's list; ``clear()`` clears the child's as well."""

    def __init__(self, items, clear) -> None:
        super().__init__(items)
        self._clear_remote = clear

    def clear(self) -> None:
        self._clear_remote()
        super().clear()


class _RemoteSet(set):
    """A copy of the child's set; ``clear()`` clears the child's as well."""

    def __init__(self, items, clear) -> None:
        super().__init__(items)
        self._clear_remote = clear

    def clear(self) -> None:
        self._clear_remote()
        super().clear()


class _HookProxy:
    def __init__(self, server: LiveServer) -> None:
        self._server = server

    @property
    def calls(self) -> list[tuple[str, float]]:
        items = [tuple(call) for call in self._server._request("get", "calls")]
        return _RemoteList(items, lambda: self._server._request("clear", "calls"))

    @property
    def threads(self) -> set[str]:
        items = self._server._request("get", "threads")
        return _RemoteSet(items, lambda: self._server._request("clear", "threads"))


class LiveServer:
    """The parent's handle on a server running in a spawned child."""

    def __init__(self, process: Any, conn: Any, ready: dict) -> None:
        self._process = process
        self._conn = conn
        self._lock = threading.Lock()
        self.hook = _HookProxy(self)
        self.loop = SimpleNamespace(thread=SimpleNamespace(name=ready["loop_thread"]))
        # The (alarm, severity) the write path was built with, read from the
        # server's own pcaspy rather than copied out of EPICS.
        self.refusal_alarm: tuple[int, int] = tuple(ready["refusal_alarm"])

    def _request(self, op: str, what: str) -> Any:
        with self._lock:
            self._conn.send((op, what))
            if not self._conn.poll(REQUEST_TIMEOUT_S):
                raise TimeoutError(f"the live CA server did not answer {op} {what}")
            return self._conn.recv()

    def close(self) -> None:
        """Stop the child cleanly; kill it if it does not go."""
        with self._lock:
            try:
                self._conn.send(("stop", None))
            except (BrokenPipeError, OSError):
                pass  # the child is already gone; the join below reaps it
        self._process.join(STOP_TIMEOUT_S)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(STOP_TIMEOUT_S)
        if self._process.is_alive():
            self._process.kill()
            self._process.join(STOP_TIMEOUT_S)
        self._conn.close()


def start(spec: dict) -> LiveServer:
    """Spawn the server process for ``spec`` and return once it is serving.

    ``spec['env']`` carries the EPICS_* settings the parent's client latched,
    so the server listens where the client searches. Raises
    :class:`ServerUnavailable` if the child cannot import pcaspy, and
    ``RuntimeError`` (with the child's traceback) if it fails any other way.
    """
    context = multiprocessing.get_context("spawn")
    parent_conn, child_conn = context.Pipe()
    process = context.Process(
        target=_child_main, args=(child_conn, spec), daemon=True, name=f"{spec['name']}-server"
    )
    process.start()
    child_conn.close()

    def abandon() -> None:
        if process.is_alive():
            process.kill()
        process.join(STOP_TIMEOUT_S)
        parent_conn.close()

    if not parent_conn.poll(START_TIMEOUT_S):
        abandon()
        raise RuntimeError("the live CA server process never reported ready")
    try:
        kind, payload = parent_conn.recv()
    except EOFError:
        abandon()
        raise RuntimeError(
            f"the live CA server process died before reporting (exit {process.exitcode})"
        ) from None
    if kind == "ready":
        return LiveServer(process, parent_conn, payload)
    abandon()
    if kind == "unavailable":
        raise ServerUnavailable(payload)
    raise RuntimeError(f"the live CA server process failed to start:\n{payload}")

"""The one event loop every Channel Access call in this process runs on.

aioca is asyncio-only and binds each channel, and each monitor, to the event
loop that opened it: it keeps one channel cache per loop and never purges the
cache of a loop that has finished. The connector is called from many loops —
the MCP server's, ``osprey.runtime``'s ``asyncio.run`` per call (a fresh
thread *and* loop per call under Jupyter), the connector host's, the
RunEngine's. Calling aioca on the caller's loop would reconnect every channel
on every call, leak a cache per call, and end a subscription with the loop
that opened it.

So every aioca call is marshalled onto one long-lived loop on one daemon
thread, shared by everything in the process. aioca's CA context is created on
that thread the first time it is used, and any other thread aioca later runs
on (ophyd-async on the RunEngine's, say) attaches to the same context.

At exit, aioca's own ``atexit`` hook purges its channels and, when it created
the context, destroys it. Nothing may still be running on the loop by then: a
channel created or read on the loop thread while the context is destroyed
under it crashes the process. So the loop is stopped, and its thread joined,
from ``threading``'s shutdown hook -- the one ``concurrent.futures`` stops its
workers from -- which runs before every ``atexit`` hook, whichever of the two
was registered first.

The context itself is then left for the process's exit to reclaim rather
than destroyed: ``ca_context_destroy`` waits out a TCP circuit still trying to
reach a name server nobody answers (an unreachable
``EPICS_CA_NAME_SERVERS`` gateway), which held a process's exit for half a
minute. aioca still clears its channels first, and makes no CA call after.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import os
import sys
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

try:
    # Runs at interpreter shutdown before any ``atexit`` hook; private, but the
    # stdlib's own ``concurrent.futures`` relies on it for the same reason.
    from threading import _register_atexit as _register_before_atexit
except ImportError:  # pragma: no cover - CPython has had it since 3.9
    _register_before_atexit = atexit.register

_THREAD_NAME = "osprey-ca-loop"

#: The environment a Channel Access context is created from.
CA_ENV_KEYS = (
    "EPICS_CA_ADDR_LIST",
    "EPICS_CA_SERVER_PORT",
    "EPICS_CA_NAME_SERVERS",
    "EPICS_CA_AUTO_ADDR_LIST",
)


def current_ca_env() -> dict[str, str | None]:
    """The ``EPICS_CA_*`` settings a context created now would run with."""
    return {key: os.environ.get(key) for key in CA_ENV_KEYS}


class CaLoop:
    """An event loop running forever on a daemon thread of its own."""

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name=_THREAD_NAME, daemon=True)
        self._thread.start()
        self._env: dict[str, str | None] | None = None
        self._used = False
        self._env_lock = threading.Lock()

    def claim_env(self, env: dict[str, str | None]) -> None:
        """Record the ``EPICS_CA_*`` settings CA is to run with; refuse a change.

        CA reads its environment once, when the context is created on the
        first call. Until a call has been made, a new claim simply replaces the
        old one. After that, a claim naming different settings raises: the
        context cannot be repointed in-process, and staying silently on the
        old settings could route a read-only run through a write gateway. A
        first call made with nothing claimed (the dispatch trigger source's,
        say) pins the environment as it was then, so it is held the same way.

        Raises before anything is recorded, so a caller can claim first and
        change ``os.environ`` only once the claim stands.
        """
        with self._env_lock:
            if self._used and env != self._env:
                raise RuntimeError(
                    "Channel Access in this process is already running with "
                    f"{self._env}; it cannot be repointed to {env} in-process. "
                    "A connector to a different gateway needs a process of its own."
                )
            if not self._used:
                self._env = dict(env)

    def _mark_used(self) -> None:
        """Record that CA has been called, pinning the environment it runs with."""
        with self._env_lock:
            if not self._used:
                self._used = True
                if self._env is None:
                    self._env = current_ca_env()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The loop itself, for callers that schedule plain callbacks on it."""
        return self._loop

    def on_loop_thread(self) -> bool:
        """True when the calling thread is this loop's own thread."""
        return threading.current_thread() is self._thread

    def _refuse_in_a_forked_child(self, coro: Coroutine[Any, Any, Any] | None = None) -> None:
        """Raise in a process forked from the one that started the loop.

        A child inherits the loop but not its thread, so work queued to it
        would wait forever; nor can it use the parent's libca context.
        """
        if os.getpid() != self._pid:
            if coro is not None:
                coro.close()
            raise RuntimeError(
                "Channel Access was started in the parent of this forked process and "
                "cannot be used here; start the child with 'spawn' or 'forkserver'."
            )

    def submit(self, coro: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        """Schedule ``coro`` on the loop, from any thread; return its future."""
        self._refuse_in_a_forked_child(coro)
        self._mark_used()
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Await ``coro`` on the CA loop from whichever loop the caller is on."""
        if self.on_loop_thread():
            self._mark_used()
            return await coro
        return await asyncio.wrap_future(self.submit(coro))

    def run_sync(self, coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
        """Run ``coro`` on the CA loop and block the calling thread for its result.

        Blocking the loop's own thread on work queued to that same loop would
        never return, so that is refused outright rather than left to hang.
        """
        if self.on_loop_thread():
            coro.close()
            raise RuntimeError("blocking on the Channel Access loop from its own thread")
        return self.submit(coro).result(timeout)

    def call_soon(self, callback: Callable[..., Any], *args: Any) -> None:
        """Run a plain callback on the loop thread, from any thread."""
        self._refuse_in_a_forked_child()
        self._loop.call_soon_threadsafe(callback, *args)

    def stop(self) -> None:
        """Stop the loop and wait briefly for its thread. Idempotent."""
        if self._loop.is_closed() or os.getpid() != self._pid:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)


_ca_loop: CaLoop | None = None
_ca_loop_lock = threading.Lock()


def _shut_down() -> None:
    """Stop the process's CA loop; leave the CA context for the exit to reclaim."""
    if _ca_loop is not None:
        _ca_loop.stop()
    catools = sys.modules.get("aioca._catools")
    if catools is not None:
        catools._Context._should_destroy = False


def get_ca_loop() -> CaLoop:
    """The process's Channel Access loop, started on first use."""
    global _ca_loop
    with _ca_loop_lock:
        if _ca_loop is None:
            _ca_loop = CaLoop()
            try:
                _register_before_atexit(_shut_down)
            except RuntimeError:
                # First used while the interpreter is already shutting down.
                atexit.register(_shut_down)
        return _ca_loop

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
the context, destroys it. That hook is registered on aioca's first use, which
is after :func:`get_ca_loop` registers the loop's shutdown, so it runs first
(``atexit`` is last-in, first-out): channels are purged while the loop that
owns them is still running, and the loop is stopped afterwards.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_THREAD_NAME = "osprey-ca-loop"


class CaLoop:
    """An event loop running forever on a daemon thread of its own."""

    def __init__(self) -> None:
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
        old settings could route a read-only run through a write gateway.
        """
        with self._env_lock:
            if self._used and self._env is not None and env != self._env:
                raise RuntimeError(
                    "Channel Access in this process is already running with "
                    f"{self._env}; it cannot be repointed to {env} in-process. "
                    "A connector to a different gateway needs a process of its own."
                )
            if not self._used:
                self._env = dict(env)

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

    def submit(self, coro: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        """Schedule ``coro`` on the loop, from any thread; return its future."""
        with self._env_lock:
            self._used = True
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Await ``coro`` on the CA loop from whichever loop the caller is on."""
        if self.on_loop_thread():
            with self._env_lock:
                self._used = True
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
        self._loop.call_soon_threadsafe(callback, *args)

    def stop(self) -> None:
        """Stop the loop and wait briefly for its thread. Idempotent."""
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)


_ca_loop: CaLoop | None = None
_ca_loop_lock = threading.Lock()


def get_ca_loop() -> CaLoop:
    """The process's Channel Access loop, started on first use."""
    global _ca_loop
    with _ca_loop_lock:
        if _ca_loop is None:
            _ca_loop = CaLoop()
            atexit.register(_ca_loop.stop)
        return _ca_loop

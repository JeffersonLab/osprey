"""Refuse raw control-system writes inside a Python process.

``install("readonly", ...)`` replaces every write entry point a table names with
a function that refuses, and closes every route out of Python that could reach
one. It is the runtime half of a readonly run: the pre-execution regex sees only
the standard spellings of a write, and ``from epics import caput as _w`` evades
it, so the refusal has to be in place before the user code runs.

This module is stdlib-only at module scope and importing it has no side effects.
Both properties are load-bearing: the executor embeds this file's *source* into
the script it runs and executes it in a private namespace, so the guard holds in
an interpreter where ``osprey`` itself cannot be imported, and no name it
defines leaks into the user code. The tables arrive as literal arguments for the
same reason — nothing here reads them from ``osprey``.

``install`` is re-entrant. A second call in the same process adds a second
finder that skips the first, wraps no loader twice, and refuses what the first
already refused.

The table covers three kinds of route: the control-system client libraries
themselves, the process-spawning surface that could shell out to ``caput``, and
``ctypes``, which reaches Channel Access without importing any client package
at all. The ``ctypes`` rows are gated rather than refused outright, because a
readonly run reads through ``osprey.runtime`` and its EPICS connector is
pyepics, which reaches Channel Access by loading ``libca`` through ``ctypes``: a
load is let through only while pyepics' own ``initialize_libca`` is on the
stack, and the handle it gets back has its put entry points refused, so the raw
route through the library is closed like every other spelling. Every other load
refuses, pyepics present or not.

Each patched attribute is also followed back to the module that defined it, so
a write a package merely re-exports refuses under both of its spellings. That
step covers the defining modules no table can enumerate — PyTango defines its
writes in ``tango.device_proxy`` and ``tango.connection`` and binds them onto
``DeviceProxy``, and every binding has its own such layout.

The two halves of the table are patched at different moments. The eager rows
(clients and escape routes) are resolved and refused at install, because a
readonly script may not import a client at all and because a client module may
load a shared library while it executes. The deferred rows (acquisition
frameworks) are refused when their module is imported, through a
``sys.meta_path`` finder that wraps the located loader, because those are the
rows a readonly script is allowed to import and a script that imports neither
should not pay for them. A framework already imported at install is patched on
the spot.
"""

import importlib
import platform
import sys
from collections.abc import Callable, Iterable
from typing import Any

#: Rows whose attributes are shared-library loaders. They are gated, not refused.
_GATED_LOADER_ROWS = ("ctypes", "ctypes.LibraryLoader")

#: Put entry points closed on the handle a permitted ``libca`` load returns.
_HANDLE_PUT_SYMBOLS = ("ca_array_put", "ca_array_put_callback")

#: Attribute every finder and loader this module installs carries, so a second
#: install recognises the first and neither delegates to the other.
_GUARD_ATTR = "_osprey_readonly_guard"

Rows = Iterable[tuple[str, Iterable[str]]]


def _pyepics_is_loading(_sys: Any = sys, _max_depth: int = 8) -> bool:
    """True while ``epics.ca.initialize_libca`` is a near caller.

    Matched by code object, not by name, so a same-named function opens nothing.
    """
    _code = getattr(
        getattr(_sys.modules.get("epics.ca"), "initialize_libca", None),
        "__code__",
        None,
    )
    if _code is None:
        return False
    # Frame 0 is this function, frame 1 the gated loader.
    _frame = _sys._getframe(2)
    for _ in range(_max_depth):
        if _frame is None:
            return False
        if _frame.f_code is _code:
            return True
        _frame = _frame.f_back
    return False


def _resolve(dotted: str) -> Any:
    """Import the longest importable prefix of *dotted*, then walk attributes.

    One spelling for modules, module attributes and classes alike. Returns None
    when the target is not present, which is the ordinary case for most of the
    table — an uninstalled library, or an optional flavour of an installed one.
    That case has to stay SILENT: it is true on every ordinary deployment, and a
    warning per absent target would print on every readonly run.
    """
    parts = dotted.split(".")
    for _cut in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:_cut]))
        except ImportError:
            continue
        for _attr in parts[_cut:]:
            try:
                obj = getattr(obj, _attr)
            except AttributeError:
                # An importable parent without the child: the target does not
                # exist here either.
                return None
        return obj
    return None


def _walk(module: Any, fullname: str, dotted: str) -> Any:
    """Walk the rest of *dotted* off *module*; None when it is not there."""
    obj = module
    for _attr in dotted.split(".")[len(fullname.split(".")) :]:
        try:
            obj = getattr(obj, _attr)
        except AttributeError:
            return None
    return obj


def install(
    mode: str,
    *,
    eager_targets: Rows,
    deferred_targets: Rows,
    refusal: str,
    replacement: Callable[..., Any] | None = None,
) -> None:
    """Refuse every write entry point in the given tables, in this process.

    *eager_targets* are resolved and refused now; *deferred_targets* are refused
    when their module is imported (or now, when it already is). Every row is a
    ``(dotted, attrs)`` pair. A refused call raises ``RuntimeError(refusal)``.

    Only ``"readonly"`` is a mode, and it refuses with a fixed function, so it
    takes no *replacement*. Failing to patch one target prints a warning naming
    it and moves on to the next; an absent target is silent.
    """
    if mode != "readonly":
        raise ValueError(f"unknown raw-put block mode: {mode!r}")
    if replacement is not None:
        raise ValueError("readonly mode refuses with a fixed function; it takes no replacement")

    # CPython resolves ``platform.uname().processor`` lazily, by shelling out to
    # ``uname -p`` on first read — and h5py reads it while ``import at``
    # initialises its type layer, so the subprocess refusal below would kill the
    # import of a pure-simulation library. Resolve it once now, while spawning
    # is still allowed; the cached value answers every later lookup without
    # touching subprocess.
    platform.processor()

    def _osprey_readonly_refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(refusal)

    def _gate_loader(_original: Callable[..., Any]) -> Callable[..., Any]:
        def _osprey_gated_load(*_args: Any, **_kwargs: Any) -> Any:
            if not _pyepics_is_loading():
                _osprey_readonly_refuse()
            _handle = _original(*_args, **_kwargs)
            try:
                for _symbol in _HANDLE_PUT_SYMBOLS:
                    setattr(_handle, _symbol, _osprey_readonly_refuse)
            except Exception:
                # A handle whose put symbols cannot be closed is not handed out
                # at all.
                _osprey_readonly_refuse()
            return _handle

        return _osprey_gated_load

    def _patch_row(dotted: str, attrs: Iterable[str], obj: Any) -> None:
        """Refuse every attribute of one row on the object it resolved to."""
        try:
            for attr in attrs:
                if not hasattr(obj, attr):
                    continue
                original = getattr(obj, attr)
                new: Callable[..., Any]
                if dotted in _GATED_LOADER_ROWS:
                    new = _gate_loader(original)
                else:
                    new = _osprey_readonly_refuse
                setattr(obj, attr, new)
                # A re-export leaves a second spelling behind that no table can
                # name for every binding. Follow the original back to the module
                # that defined it and refuse there too. The identity check is
                # what makes this safe to run generically: ``__module__`` and
                # ``__name__`` are metadata a decorator or a rebind can leave
                # pointing at a module holding something else entirely, and
                # replacing an attribute on a name match alone could silently
                # refuse an unrelated read.
                try:
                    home = sys.modules.get(getattr(original, "__module__", None))  # type: ignore[arg-type]
                    name = getattr(original, "__name__", None)
                    if (
                        home is not None
                        and isinstance(name, str)
                        and getattr(home, name, None) is original
                    ):
                        setattr(home, name, new)
                except Exception as home_error:
                    # Secondary, best-effort step: the attribute the table names
                    # already refuses. A failure here — an unhashable
                    # ``__module__``, a module ``__getattr__`` that raises — must
                    # name the attribute and let the REST of the row be patched,
                    # so it is caught here rather than at the row level.
                    print(
                        f"⚠️  readonly guard ({dotted}.{attr}) "
                        f"defining-module step failed: {home_error}"
                    )
            # pvaPy spells one typed setter per scalar and array type
            # (putDouble, putScalarArray, ...). Enumerating them would go stale
            # against the binding; the prefix will not. Three writes sit outside
            # that prefix — asyncPut, parsePut and parsePutGet — and they reach
            # the machine exactly as the rest do, so they are swept with them.
            if dotted == "pvaccess.Channel":
                for attr in dir(obj):
                    if attr.startswith(("put", "asyncPut", "parsePut")):
                        setattr(obj, attr, _osprey_readonly_refuse)
        except Exception as guard_error:
            # A target that cannot be patched must not stop the ones after it,
            # and the operator needs to know which one.
            print(f"⚠️  readonly guard ({dotted}) failed: {guard_error}")

    # The eager rows are resolved before the loader is gated, in table order,
    # because a client module may load a shared library while it executes:
    # ``epicscorelibs.ca.cadef`` loads ``libca`` through ``ctypes.CDLL`` in its
    # module body, and that row precedes the ``ctypes`` rows.
    for dotted, attrs in eager_targets:
        try:
            obj = _resolve(dotted)
        except Exception as guard_error:
            print(f"⚠️  readonly guard ({dotted}) failed: {guard_error}")
            continue
        if obj is None:
            continue
        _patch_row(dotted, attrs, obj)

    # The deferred rows wait for the script's own import. Each row is indexed
    # under every module prefix of its dotted name, so it is reconsidered as
    # each module on its path finishes executing; a key that never names a
    # module simply never fires.
    rows_by_module: dict[str, list[tuple[str, Iterable[str]]]] = {}
    for dotted, attrs in deferred_targets:
        parts = dotted.split(".")
        for cut in range(1, len(parts) + 1):
            rows_by_module.setdefault(".".join(parts[:cut]), []).append((dotted, attrs))

    def _patch_module(fullname: str, module: Any) -> None:
        for dotted, attrs in rows_by_module.get(fullname, ()):
            obj = _walk(module, fullname, dotted)
            if obj is not None:
                _patch_row(dotted, attrs, obj)

    class _OspreyReadonlyGuardLoader:
        """Run the located loader, then refuse the writes its module defines."""

        _osprey_readonly_guard = True

        def __init__(self, loader: Any) -> None:
            self._osprey_loader = loader

        def create_module(self, spec: Any) -> Any:
            return self._osprey_loader.create_module(spec)

        def exec_module(self, module: Any) -> None:
            self._osprey_loader.exec_module(module)
            try:
                _patch_module(module.__name__, module)
            except Exception as error:
                print(f"⚠️  readonly guard ({module.__name__}) failed: {error}")

        def __getattr__(self, name: str) -> Any:
            # Everything else a loader answers (get_code, is_package,
            # get_source, ...) is the located loader's answer.
            if name == "_osprey_loader":
                raise AttributeError(name)
            return getattr(self._osprey_loader, name)

    class _OspreyReadonlyGuardFinder:
        """Wrap the loader of every module a deferred write target lives in."""

        _osprey_readonly_guard = True

        def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
            if fullname not in rows_by_module:
                return None
            for finder in sys.meta_path:
                # Every guard finder is skipped, not only this one: two guards
                # delegating to each other would never return.
                if getattr(finder, _GUARD_ATTR, False):
                    continue
                find_spec = getattr(finder, "find_spec", None)
                if find_spec is None:
                    continue
                spec = find_spec(fullname, path, target)
                if spec is not None:
                    break
            else:
                return None
            loader = spec.loader
            # A namespace package or a legacy loader carries no write target's
            # definition; wrapping it would change how the module is created.
            if (
                loader is not None
                and hasattr(loader, "exec_module")
                and not getattr(loader, _GUARD_ATTR, False)
            ):
                spec.loader = _OspreyReadonlyGuardLoader(loader)
            return spec

    sys.meta_path.insert(0, _OspreyReadonlyGuardFinder())  # type: ignore[arg-type]
    for name in list(sys.modules):
        if name in rows_by_module:
            module = sys.modules.get(name)
            if module is not None:
                _patch_module(name, module)

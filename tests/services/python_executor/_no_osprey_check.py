"""Check that the emitted raw-put block holds in an interpreter without osprey.

Usage: ``python tests/services/python_executor/_no_osprey_check.py readonly``

The executor embeds the guard into the script it runs, and that script must
refuse a raw put even where ``osprey`` and ``osprey_connectors`` cannot be
imported. This emits the guard here, then runs it in a fresh interpreter with
both packages blocked, and asserts that a raw put refuses with the readonly
marker. Exits non-zero on any failure. Not collected by pytest (leading
underscore); it is a gate helper.
"""

import subprocess
import sys
import textwrap

from osprey.services.python_executor.execution.wrapper import (
    READONLY_REFUSAL_MARKER,
    ExecutionWrapper,
)

_PROBE = textwrap.dedent(
    """
    import sys
    import types

    sys.modules["osprey"] = None  # any `import osprey` now raises ImportError
    sys.modules["osprey_connectors"] = None

    # A stand-in client, so the check does not depend on what is installed.
    epics = types.ModuleType("epics")
    epics.caput = lambda *_a, **_k: "wrote"
    sys.modules["epics"] = epics

    exec(compile(sys.stdin.read(), "<emitted guard>", "exec"), {})

    marker = sys.argv[1]
    for name, attempt in (
        ("epics.caput", lambda: epics.caput("SR:PV", 1.0)),
        ("ctypes.CDLL", lambda: __import__("ctypes").CDLL(None)),
    ):
        try:
            attempt()
        except RuntimeError as error:
            if marker not in str(error):
                sys.exit(f"{name}: refused without the marker: {error}")
        else:
            sys.exit(f"{name}: raw put was NOT refused")
    try:
        import osprey  # noqa: F401
    except ImportError:
        pass
    else:
        sys.exit("osprey was importable inside the probe")
    print("ok")
    """
)


def _emit(mode: str) -> str:
    if mode == "readonly":
        return ExecutionWrapper(execution_mode="readonly")._get_readonly_guard()
    raise SystemExit(f"unknown mode {mode!r}; expected: readonly")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    source = _emit(argv[1])
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, READONLY_REFUSAL_MARKER],
        input=source,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or result.stdout.strip() != "ok":
        print(f"FAIL ({argv[1]}): exit {result.returncode}", file=sys.stderr)
        print(f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}", file=sys.stderr)
        return 1
    print(f"ok ({argv[1]}): raw put refused with osprey blocked")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

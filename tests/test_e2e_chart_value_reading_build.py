"""The beam-loss benchmark builds with the model the run names, subagents included.

A subagent runs the model id the build wrote into its definition, and the plot
in ``tests/e2e/tier2/test_chart_value_reading.py`` is read inside the
``logbook-search`` subagent. A build that names no model takes the provider
catalog's default, and the benchmark then scores that model whatever the lane
or the matrix cell asked for. Pinned here without a deploy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.provider import E2E_MODEL, FORCE_MODEL_ENV
from tests.e2e.tier2 import test_chart_value_reading as benchmark


def _model_edits(args: list[str]) -> list[str]:
    return [a for a in args if a.startswith("model=")]


def test_init_names_the_suite_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OSPREY_E2E_PROVIDER", "als-apg")
    monkeypatch.delenv(FORCE_MODEL_ENV, raising=False)
    assert _model_edits(benchmark._init_args(tmp_path / "repo")) == [f"model={E2E_MODEL}"]


def test_init_names_the_forced_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OSPREY_E2E_PROVIDER", "als-apg")
    monkeypatch.setenv(FORCE_MODEL_ENV, "claude-opus-5-5")
    assert _model_edits(benchmark._init_args(tmp_path / "repo")) == ["model=claude-opus-5-5"]

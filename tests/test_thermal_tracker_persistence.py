"""Thermal cycle state is written off the event loop without losing order."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from homeintent.thermal_tracker import ThermalExperienceTracker  # noqa: E402


def test_an_older_document_never_replaces_a_newer_one(tmp_path):
    path = tmp_path / "cycles.json"
    tracker = ThermalExperienceTracker(SimpleNamespace(), state_path=path)

    older = tracker._next_document()
    newer = (older[0] + 1, {"schema_version": 1, "cycles": ["newer"]})
    tracker._write_generation(*newer)
    # The older write finishes last, as it could from another worker thread.
    tracker._write_generation(*older)

    assert json.loads(path.read_text(encoding="utf-8"))["cycles"] == ["newer"]


def test_async_persist_writes_the_current_state(tmp_path):
    import asyncio

    path = tmp_path / "cycles.json"
    tracker = ThermalExperienceTracker(SimpleNamespace(), state_path=path)

    asyncio.run(tracker._async_persist())

    assert json.loads(path.read_text(encoding="utf-8")) == {"cycles": [], "schema_version": 1}

"""The engine is built and warmed up off Home Assistant's event loop."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import homeintent as homeintent_init  # noqa: E402
from homeintent.engine import NluEngine  # noqa: E402


def test_build_engine_returns_a_warmed_up_engine():
    engine = homeintent_init._build_engine()

    assert isinstance(engine, NluEngine)
    # Warming up must not leave any parse state behind.
    assert engine.match_relative_time_automation is not None


def test_warm_up_is_repeatable_and_side_effect_free():
    engine = NluEngine()

    engine.warm_up()
    engine.warm_up()

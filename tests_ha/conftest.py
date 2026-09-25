"""Fixtures for tests that run against a REAL Home Assistant install.

This directory is deliberately separate from ``tests/``: the main suite
injects a lightweight ``homeassistant`` stub into ``sys.modules``
(``tests/_ha_stub.py``), which must never share a process with the real
package. Run with ``requirements-ha-test.txt`` installed::

    python -m pytest tests_ha
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Home Assistant imports custom integrations as ``custom_components.<domain>``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let the loader find ``custom_components/homeintent``."""
    yield

"""Unit tests for automation_summary.AutomationSummary (HomeIntent V5 Teil
9/10, V5.29 "Automation Query") - hass-free, plain dataclass construction/
defaults/equality, same style as test_devices.py's DeviceSnapshot coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from ha_nlu.automation_summary import AutomationSummary  # noqa: E402


def test_automation_summary_defaults():
    automation = AutomationSummary(automation_id="abc123", alias="Meine Automation")

    assert automation.source_text is None
    assert automation.created_by is None
    assert automation.referenced_entity_ids == frozenset()


def test_automation_summary_full_fields():
    automation = AutomationSummary(
        automation_id="abc123",
        alias="Küchenlicht-Automation",
        source_text="Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.",
        created_by="homeintent",
        referenced_entity_ids=frozenset({"binary_sensor.kueche_fenster", "light.kueche_licht"}),
    )

    assert automation.source_text == "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein."
    assert automation.created_by == "homeintent"
    assert automation.referenced_entity_ids == frozenset(
        {"binary_sensor.kueche_fenster", "light.kueche_licht"}
    )


def test_automation_summary_equality_is_value_based():
    a = AutomationSummary(automation_id="abc123", alias="Meine Automation")
    b = AutomationSummary(automation_id="abc123", alias="Meine Automation")

    assert a == b

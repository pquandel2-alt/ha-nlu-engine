from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ha_nlu.advanced_queries import match_advanced_query
from ha_nlu.entities import EntitySnapshot
from ha_nlu.phonetic_correction import phonetic_suggestions
from ha_nlu.security_control import match_alarm_control


NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)


def test_household_health_queries_are_derived_from_live_snapshot():
    entities = [
        EntitySnapshot("sensor.battery", "Türakku", "sensor", "12", device_class="battery"),
        EntitySnapshot("sensor.power", "Waschmaschine Leistung", "sensor", "850", unit="W", device_class="power"),
        EntitySnapshot("light.offline", "Flurlicht", "light", "unavailable"),
    ]
    assert "Türakku" in match_advanced_query("Welche Batterien sind unter 20 Prozent?", entities, NOW)
    assert "850 Watt" in match_advanced_query("Wer verbraucht am meisten Strom?", entities, NOW)
    assert "Flurlicht" in match_advanced_query("Welche Geräte sind nicht erreichbar?", entities, NOW)


def test_long_open_window_uses_real_last_changed_timestamp():
    window = EntitySnapshot(
        "binary_sensor.fenster", "Badfenster", "binary_sensor", "on",
        device_class="window", last_changed=NOW - timedelta(hours=3),
    )
    answer = match_advanced_query(
        "Welche Fenster sind seit mehr als zwei Stunden offen?", [window], NOW
    )
    assert "Badfenster" in answer


def test_alarm_disarm_is_admin_gated_and_always_confirmed():
    alarm = EntitySnapshot(
        "alarm_control_panel.haus", "Hausalarm", "alarm_control_panel", "armed_away"
    )
    denied = match_alarm_control("Schalte die Alarmanlage unscharf", [alarm], allow_disarm=False)
    allowed = match_alarm_control("Schalte die Alarmanlage unscharf", [alarm], allow_disarm=True)
    assert denied.plan is None
    assert allowed.plan.service == "alarm_disarm"
    assert allowed.requires_confirmation is True


def test_asr_correction_only_suggests_selected_entity_vocabulary():
    entity = EntitySnapshot("cover.buero", "Büro Rollladen", "cover", "open")
    suggestions = phonetic_suggestions("Fahre den Büro Roladen runter", [entity])
    assert any("rollladen" in item.corrected_text.casefold() for item in suggestions)

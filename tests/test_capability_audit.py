"""The spoken readiness audit reflects only selected snapshot data."""

import pytest

from ha_nlu.capability_audit import audit_capabilities, match_capability_audit_query
from ha_nlu.entities import EntitySnapshot


ENTITIES = [
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "off",
        area_id="kueche", area_name="Küche",
    ),
    EntitySnapshot("vacuum.atlas", "Saugroboter Atlas", "vacuum", "docked"),
    EntitySnapshot("sensor.temperatur", "Außentemperatur", "sensor", "22"),
    EntitySnapshot("calendar.familie", "Familienkalender", "calendar", "on"),
    EntitySnapshot("siren.garage", "Garagensirene", "siren", "off"),
]


def test_capability_audit_classifies_snapshot_without_runtime_calls():
    result = audit_capabilities(ENTITIES)

    assert result.selected_count == 5
    assert {entity.entity_id for entity in result.controllable} == {
        "light.kueche", "vacuum.atlas",
    }
    assert [entity.entity_id for entity in result.unsupported] == ["siren.garage"]
    assert [entity.entity_id for entity in result.missing_area] == ["vacuum.atlas"]


@pytest.mark.parametrize(
    ("question", "expected"),
    (
        ("Ist HomeIntent bereit?", "5 freigegebene Entities"),
        ("Welche Geräte kannst du steuern?", "1 Lichter"),
        ("Welche Geräte kannst du nicht steuern?", "Garagensirene"),
        ("Welche Geräte haben keinen Bereich?", "Saugroboter Atlas"),
        ("Warum kannst du die Garagensirene nicht steuern?", "noch keinen sicheren HomeIntent-Adapter"),
        ("Warum kannst du die Außentemperatur nicht steuern?", "lesende sensor-Entity"),
    ),
)
def test_capability_audit_questions_are_read_only(question, expected):
    result = match_capability_audit_query(question, ENTITIES)

    assert result is not None, question
    assert result.plan is None
    assert result.is_query
    assert expected in result.response_text


def test_capability_audit_does_not_claim_unrelated_language():
    assert match_capability_audit_query("Starte den Saugroboter", ENTITIES) is None

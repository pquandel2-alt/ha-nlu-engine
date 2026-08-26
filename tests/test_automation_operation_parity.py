"""Safe direct device operations keep their meaning in automations."""

from __future__ import annotations

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionType
from ha_nlu.nlu.automation_model import AutomationModel, TriggerModel, TriggerType
from ha_nlu.nlu.ha_automation_generator import generate_ha_automation_config


@pytest.fixture
def parity_entities():
    return [
        EntitySnapshot("vacuum.atlas", "Saugroboter Atlas", "vacuum", "docked"),
        EntitySnapshot(
            "media_player.tv", "Wohnzimmer Fernseher", "media_player", "idle",
            attributes={"source_list": ["TV", "Netflix"]},
        ),
        EntitySnapshot("scene.filmabend", "Filmabend", "scene", "2026-08-26T10:00:00"),
        EntitySnapshot(
            "humidifier.bad", "Luftbefeuchter Bad", "humidifier", "on",
            attributes={"humidity": 40, "min_humidity": 30, "max_humidity": 80},
        ),
        EntitySnapshot(
            "climate.buero", "Heizung Büro", "climate", "heat",
            attributes={"hvac_modes": ["heat", "auto"], "temperature": 21},
        ),
        EntitySnapshot("cover.buero", "Jalousie Büro", "cover", "open"),
        EntitySnapshot(
            "select.profil", "Heizprofil", "select", "Komfort",
            attributes={"options": ["Eco", "Komfort"]},
        ),
        EntitySnapshot(
            "lawn_mower.garten", "Mähroboter Garten", "lawn_mower", "docked",
            attributes={"supported_features": 7},
        ),
        EntitySnapshot("lock.haustuer", "Haustür", "lock", "locked"),
        EntitySnapshot("button.reset", "Reset Taste", "button", "unknown"),
        EntitySnapshot(
            "binary_sensor.fenster", "Küchenfenster", "binary_sensor", "off",
            area_id="kueche", area_name="Küche", device_class="window",
        ),
    ]


@pytest.mark.parametrize(
    ("sentence", "domain", "service"),
    (
        ("Starte in 5 Minuten den Saugroboter Atlas", "vacuum", "start"),
        ("Pausiere in 5 Minuten die Wiedergabe auf dem Wohnzimmer Fernseher", "media_player", "media_pause"),
        ("Aktiviere in 5 Minuten die Szene Filmabend", "scene", "turn_on"),
        ("Stelle in 5 Minuten den Luftbefeuchter Bad auf 45 Prozent Luftfeuchtigkeit", "humidifier", "set_humidity"),
        ("Stelle in 5 Minuten die Heizung Büro auf Automatik", "climate", "set_hvac_mode"),
        ("Stelle in 5 Minuten die Lamellen der Jalousie Büro auf 35 Prozent", "cover", "set_cover_tilt_position"),
        ("Wähle in 5 Minuten beim Heizprofil Eco", "select", "select_option"),
        ("Schicke in 5 Minuten den Mähroboter Garten zur Ladestation", "lawn_mower", "dock"),
    ),
)
def test_relative_time_uses_registered_direct_operation(
    engine, parity_entities, sentence, domain, service
):
    result = engine.match_relative_time_automation(sentence, parity_entities)
    assert result is not None, sentence
    assert result.validation_error is None
    action = result.model.actions[0]
    assert action.type is ActionType.REGISTERED_SERVICE
    assert (action.service_domain, action.service_name) == (domain, service)


@pytest.mark.parametrize(
    ("sentence", "domain", "service"),
    (
        ("Starte morgen um 8 Uhr den Saugroboter Atlas", "vacuum", "start"),
        ("Pausiere morgen um 8 Uhr die Wiedergabe auf dem Wohnzimmer Fernseher", "media_player", "media_pause"),
        ("Aktiviere morgen um 8 Uhr die Szene Filmabend", "scene", "turn_on"),
    ),
)
def test_calendar_time_uses_same_action_pipeline(
    engine, parity_entities, sentence, domain, service
):
    result = engine.match_calendar_time_automation(sentence, parity_entities)
    assert result is not None, sentence
    action = result.model.actions[0]
    assert action.type is ActionType.REGISTERED_SERVICE
    assert (action.service_domain, action.service_name) == (domain, service)


def test_registered_operation_generates_only_registered_native_action(engine, parity_entities):
    parsed = engine.match_relative_time_automation(
        "Pausiere in 5 Minuten die Wiedergabe auf dem Wohnzimmer Fernseher",
        parity_entities,
    )
    action = parsed.model.actions[0]
    model = AutomationModel(
        triggers=(TriggerModel(type=TriggerType.TIME, time_hour=8),),
        actions=(action,),
    )
    generated = generate_ha_automation_config(model, parity_entities)
    assert generated.error is None
    assert generated.config["actions"] == [{
        "action": "media_player.media_pause",
        "target": {"entity_id": "media_player.tv"},
    }]


def test_state_triggered_automation_uses_same_registered_action(engine, parity_entities):
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird, starte den Saugroboter Atlas",
        parity_entities,
    )
    assert result is not None
    assert result.validation_error is None
    action = result.model.actions[0]
    assert action.type is ActionType.REGISTERED_SERVICE
    assert (action.service_domain, action.service_name) == ("vacuum", "start")


@pytest.mark.parametrize("sentence", (
    "Entriegle in 5 Minuten die Haustür",
    "Drücke in 5 Minuten die Reset Taste",
))
def test_high_risk_direct_services_are_not_lifted_into_automations(
    engine, parity_entities, sentence
):
    assert engine.match_relative_time_automation(sentence, parity_entities) is None

"""Read-only household questions are deterministic and never executable."""

from datetime import datetime, timezone

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.household_query import match_household_query
from ha_nlu.nlu.language_frontend import analyse_language


NOW = datetime(2026, 8, 26, 14, 7, tzinfo=timezone.utc)
ENTITIES = [
    EntitySnapshot("person.philipp", "Philipp", "person", "home"),
    EntitySnapshot("person.anna", "Anna", "person", "not_home"),
    EntitySnapshot(
        "weather.home", "Wetter Zuhause", "weather", "partlycloudy",
        attributes={
            "temperature": 23.4,
            "humidity": 58,
            "forecast": [
                {"datetime": "2026-08-27T12:00:00+00:00", "condition": "sunny", "temperature": 25, "templow": 14}
            ],
        },
    ),
    EntitySnapshot(
        "sun.sun", "Sonne", "sun", "above_horizon",
        attributes={
            "next_rising": "2026-08-27T04:31:00+00:00",
            "next_setting": "2026-08-26T18:19:00+00:00",
        },
    ),
    EntitySnapshot("scene.filmabend", "Filmabend", "scene", "unknown"),
    EntitySnapshot("script.gute_nacht", "Gute Nacht", "script", "off"),
    EntitySnapshot(
        "media_player.tv", "Wohnzimmer Fernseher", "media_player", "idle",
        area_id="wohnzimmer", area_name="Wohnzimmer",
        attributes={"source_list": ["TV", "Netflix"]},
    ),
    EntitySnapshot(
        "climate.buero", "Heizung Büro", "climate", "heat",
        area_id="buero", area_name="Büro",
        attributes={"hvac_modes": ["heat", "auto"]},
    ),
    EntitySnapshot("sensor.remote_battery", "Fernbedienung Batterie", "sensor", "12", device_class="battery"),
    EntitySnapshot("sensor.phone_battery", "Handy Batterie", "sensor", "72", device_class="battery"),
]


@pytest.mark.parametrize(
    ("question", "expected"),
    (
        ("Wie spät ist es?", "14:07 Uhr"),
        ("Welches Datum haben wir?", "Mittwoch, der 26. August 2026"),
        ("Wer ist zuhause?", "Zuhause: Philipp"),
        ("Ist Anna zuhause?", "Anna ist laut Home Assistant nicht zuhause"),
        ("Wie ist das Wetter?", "teilweise bewölkt, 23.4 Grad"),
        ("Wie wird das Wetter morgen?", "Morgen wird es sonnig, bis 25 Grad"),
        ("Welche Batterien sind unter 20 Prozent?", "Fernbedienung Batterie mit 12 Prozent"),
        ("Gibt es Probleme im Haus?", "Schwache Batterien: Fernbedienung Batterie"),
        ("Wann geht die Sonne unter?", "heute um 18:19 Uhr unter"),
        ("Wann geht die Sonne auf?", "morgen um 04:31 Uhr auf"),
        ("Welche Szenen gibt es?", "Verfügbare Szenen: Filmabend"),
        ("Welche Skripte sind verfügbar?", "Verfügbare Skripte: Gute Nacht"),
        ("Welche Quellen hat der Fernseher im Wohnzimmer?", "TV, Netflix"),
        ("Welche Modi hat die Heizung im Büro?", "heat, auto"),
        ("Was kann der Fernseher im Wohnzimmer?", "Wiedergabe steuern"),
        ("Was kannst du?", "Automationen und Erinnerungen erstellen"),
    ),
)
def test_household_query_answers_from_snapshot_without_service_plan(question, expected):
    result = match_household_query(question, ENTITIES, NOW)

    assert result is not None, question
    assert result.plan is None
    assert expected in result.response_text


@pytest.mark.parametrize(
    "text",
    (
        "Schalte den Fernseher ein",
        "Vielleicht ist morgen schönes Wetter",
        "Erzähle mir einen Witz",
    ),
)
def test_household_query_does_not_claim_commands_or_unrelated_language(text):
    assert match_household_query(text, ENTITIES, NOW) is None


def test_shared_language_document_is_authoritative_for_query_routing():
    command_document = analyse_language("Schalte das Wohnzimmerlicht ein", ENTITIES)

    assert match_household_query(
        "Wie spät ist es?", ENTITIES, NOW, command_document
    ) is None


def test_explicit_outdoor_sensor_question_is_not_claimed_as_general_weather():
    entities = ENTITIES + [
        EntitySnapshot(
            "sensor.aussentemperatur_sensor_temperature",
            "Außentemperatur Sensor Temperatur",
            "sensor",
            "30.4",
            unit="°C",
            device_class="temperature",
        )
    ]

    result = match_household_query(
        "Welche Temperatur zeigt der Außentemperatur-Sensor?", entities, NOW
    )

    assert result is None

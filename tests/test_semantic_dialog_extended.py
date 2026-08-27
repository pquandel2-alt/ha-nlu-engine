from ha_nlu.entities import EntitySnapshot
from ha_nlu.semantic_dialog import continue_semantic_dialog, start_semantic_dialog


def test_humidifier_missing_value_is_completed_generically():
    entity = EntitySnapshot(
        "humidifier.bed", "Luftbefeuchter Schlafzimmer", "humidifier", "on",
        attributes={"min_humidity": 30, "max_humidity": 70},
    )
    start = start_semantic_dialog("Stelle die Luftfeuchtigkeit vom Luftbefeuchter Schlafzimmer ein", [entity])
    assert start is not None and start.pending is not None
    done = continue_semantic_dialog("Bitte auf 55 Prozent", start.pending)
    assert done.result is not None
    assert done.result.plan.data == {"humidity": 55.0}


def test_select_missing_option_lists_and_accepts_supported_option():
    entity = EntitySnapshot(
        "select.air", "Lüftungsprofil", "select", "Normal",
        attributes={"options": ["Normal", "Intensiv"]},
    )
    start = start_semantic_dialog("Stelle das Lüftungsprofil ein", [entity])
    assert start is not None and start.pending is not None
    rejected = continue_semantic_dialog("etwas stärker", start.pending)
    assert "Intensiv" in rejected.question
    done = continue_semantic_dialog("Intensiv", start.pending)
    assert done.result is not None
    assert done.result.plan.data == {"option": "Intensiv"}


def test_percentage_without_temperature_cue_never_starts_climate_dialog():
    """A percentage is not a temperature merely because parsing failed."""
    climates = [
        EntitySnapshot(
            "climate.kitchen", "Heizung Küche", "climate", "heat",
            capabilities=frozenset({"TEMPERATURE"}),
        ),
        EntitySnapshot(
            "climate.bath", "Heizung Bad", "climate", "heat",
            capabilities=frozenset({"TEMPERATURE"}),
        ),
    ]

    outcome = start_semantic_dialog(
        "Fahre die Rollläden im unbekannten Raum auf 30 Prozent", climates
    )

    assert outcome is None

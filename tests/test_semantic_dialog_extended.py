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

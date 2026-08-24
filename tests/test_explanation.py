"""Transparent user-facing rendering of resolved semantic plans."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.command import SemanticCommand
from ha_nlu.nlu.explanation import explain_command, is_explanation_request
from ha_nlu.nlu.frame import SemanticFrame, TargetReference


def test_explanation_request_is_meaning_based_but_bounded():
    assert is_explanation_request("Was hast du gerade verstanden?")
    assert is_explanation_request("Wie hast du das verstanden?")
    assert is_explanation_request("Welchen Befehl hast du verstanden?")
    assert not is_explanation_request("Verstehst du eigentlich Deutsch?")


def test_explanation_names_resolved_action_targets_value_and_exclusions():
    entities = (
        EntitySnapshot("cover.wohnzimmer", "Wohnzimmerrollladen", "cover", "open"),
        EntitySnapshot("cover.kueche", "Küchenrollladen", "cover", "open"),
    )
    frame = SemanticFrame(
        intent="HassSetPercentage",
        target=TargetReference("cover", domain="cover"),
        area=None,
        parameters={
            "percent": 50,
            "excluded": ("Bürorolladen",),
            "locations": (
                {"text": "Wohnzimmer", "area_id": "wohnzimmer", "floor_id": None},
                {"text": "Küche", "area_id": "kueche", "floor_id": None},
            ),
        },
    )
    command = SemanticCommand(
        intent=frame.intent,
        entities=entities,
        area=None,
        parameters=frame.parameters,
        source_frame=frame,
    )

    explanation = explain_command(command)

    assert "auf einen Prozentwert stellen" in explanation
    assert "Wohnzimmerrollladen, Küchenrollladen" in explanation
    assert "Orte: Wohnzimmer, Küche" in explanation
    assert "Wert: 50 Prozent" in explanation
    assert "Ausgenommen: Bürorolladen" in explanation

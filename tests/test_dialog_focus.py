from __future__ import annotations

from ha_nlu.nlu.dialog_focus import derive_dialog_focus
from ha_nlu.nlu.primitives import SemanticProperty


def test_focus_tracks_floor_property_and_candidates(engine):
    from test_language_understanding_expansion import ENTITIES

    result = engine.match("Wie hoch ist die Temperatur im Erdgeschoss?", ENTITIES)
    focus = derive_dialog_focus(result.command)

    assert focus.property is SemanticProperty.TEMPERATURE
    assert focus.scope_kind == "floor"
    assert focus.scope_id == "eg"
    assert set(focus.candidate_entity_ids) == {
        "sensor.wohnzimmer_temp",
        "sensor.kueche_temp",
    }


def test_focus_infers_percentage_property_from_domain(engine, entities):
    result = engine.match("Stelle Rollladen Büro auf 40 Prozent", entities)
    focus = derive_dialog_focus(result.command)

    assert focus.property is SemanticProperty.POSITION
    assert focus.scope_kind == "entity"

"""Constraint Resolver (V6.9): resolve_candidates() finds every entity that
satisfies ALL given constraints (AND semantics), before any Quantity is
applied. Capability Reasoning (V6.8) is exercised here via the ``property``
constraint - see test_capabilities.py for required_capability_for_property()
itself."""

from __future__ import annotations

from ha_nlu.nlu.constraint_resolver import Constraints, resolve_candidates
from ha_nlu.nlu.primitives import SemanticProperty


def test_empty_constraints_matches_every_entity(entities):
    assert resolve_candidates(entities, Constraints()) == entities


def test_domain_constraint_filters_to_matching_domain(entities):
    result = resolve_candidates(entities, Constraints(domain="light"))
    assert result
    assert all(e.domain == "light" for e in result)


def test_domain_and_area_constraint_combine(quantifier_entities):
    result = resolve_candidates(
        quantifier_entities, Constraints(domain="cover", area_id="poleraum")
    )
    assert {e.entity_id for e in result} == {
        "cover.rolllade_poleraum_links", "cover.rolllade_poleraum_rechts",
    }


def test_area_constraint_without_domain_filters_across_domains():
    from ha_nlu.entities import EntitySnapshot

    entities = [
        EntitySnapshot("light.a", "Lampe A", "light", "off", area_id="buero"),
        EntitySnapshot("switch.b", "Schalter B", "switch", "off", area_id="buero"),
        EntitySnapshot("light.c", "Lampe C", "light", "off", area_id="kueche"),
    ]
    result = resolve_candidates(entities, Constraints(area_id="buero"))
    assert {e.entity_id for e in result} == {"light.a", "switch.b"}


def test_property_constraint_keeps_only_entities_with_required_capability(entities):
    """The ``entities`` fixture's lights carry BRIGHTNESS but not COLOR
    (see conftest.py's ALL_ENTITIES) - a real, grounded capability gap."""
    result = resolve_candidates(
        entities, Constraints(domain="light", property=SemanticProperty.BRIGHTNESS)
    )
    assert result

    result = resolve_candidates(
        entities, Constraints(domain="light", property=SemanticProperty.COLOR)
    )
    assert result == []


def test_device_class_constraint_filters_sensors(sensor_entities):
    result = resolve_candidates(
        sensor_entities, Constraints(domain="sensor", device_class="temperature")
    )
    assert [e.entity_id for e in result] == ["sensor.aussentemperatur"]

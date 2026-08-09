"""HassGetState: sensor state queries. No service call - only speech."""

from __future__ import annotations


def test_wie_hoch_ist_die_aussentemperatur(engine, sensor_entities):
    # Verbatim regression case from the real-world requirement.
    result = engine.match("wie hoch ist die Außentemperatur?", sensor_entities)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "18.4 Grad."


def test_wie_ist_luftfeuchtigkeit_bad(engine, sensor_entities):
    result = engine.match("wie ist die Luftfeuchtigkeit Bad?", sensor_entities)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "52 Prozent."


def test_query_unknown_entity_returns_none(engine, sensor_entities):
    assert engine.match("wie hoch ist die Kellertemperatur", sensor_entities) is None


def test_query_wrong_domain_returns_none(engine, entities):
    # Query intents are scoped to sensor - a cover must not answer a query.
    assert engine.match("wie ist der Rollladen Büro", entities) is None


def test_query_case_does_not_matter(engine, sensor_entities):
    # Also incidentally umlaut-tolerant since Phase 5 (Alias-System): the
    # entity_id "sensor.aussentemperatur" is ASCII by HA convention, so its
    # generated entity_name alias "Aussentemperatur" matches "AUSSENTEMPERATUR"
    # - a real alternate-name match, not umlaut normalization/guessing.
    result = engine.match("WIE HOCH IST DIE AUSSENTEMPERATUR", sensor_entities)
    assert result is not None
    assert result.response_text == "18.4 Grad."

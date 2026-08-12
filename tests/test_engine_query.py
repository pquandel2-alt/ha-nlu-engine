"""HassGetState: sensor state / light brightness queries (v2 plan Phase 18,
"Query Engine"). No service call - only speech."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot

DIMMED_LIGHT = EntitySnapshot(
    "light.wohnzimmer_decke", "Wohnzimmer Decke", "light", "on", attributes={"brightness": 128}
)
ONOFF_LIGHT = EntitySnapshot("light.flur", "Flur", "light", "on")
OFF_LIGHT = EntitySnapshot(
    "light.keller", "Keller", "light", "off", attributes={"brightness": 255}
)

LIGHT_QUERY_ENTITIES = [DIMMED_LIGHT, ONOFF_LIGHT, OFF_LIGHT]


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


def test_welche_temperatur_zeigt_der_sensor(engine, sensor_entities):
    # Live gap (v4.1.2, screenshot IMG_3105): "Welche Temperatur zeigt der
    # {name} Sensor?" - the attribute word ("Temperatur") is not a slot,
    # HassGetState's response is derived from the resolved entity itself
    # (see query.yaml's comment), so this must resolve identically to
    # test_wie_hoch_ist_die_aussentemperatur above.
    result = engine.match("Welche Temperatur zeigt der Außentemperatur Sensor?", sensor_entities)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "18.4 Grad."


def test_was_zeigt_der_sensor_an(engine, sensor_entities):
    result = engine.match("Was zeigt der Außentemperatur Sensor an?", sensor_entities)
    assert result is not None
    assert result.response_text == "18.4 Grad."


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


def test_wie_hell_ist_dimmed_light_speaks_percentage(engine):
    result = engine.match("wie hell ist die Wohnzimmer Decke", LIGHT_QUERY_ENTITIES)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "50 Prozent."


def test_wie_hell_ist_onoff_light_without_brightness_attribute(engine):
    result = engine.match("wie hell ist die Flur", LIGHT_QUERY_ENTITIES)
    assert result is not None
    assert result.response_text == "an."


def test_wie_hell_ist_off_light_ignores_stale_brightness_attribute(engine):
    result = engine.match("wie hell ist die Keller", LIGHT_QUERY_ENTITIES)
    assert result is not None
    assert result.response_text == "aus."


def test_wie_ist_waschmaschine_speaks_power(engine, sensor_entities):
    result = engine.match("wie ist die Waschmaschine?", sensor_entities)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "1200 Watt."


def test_wie_viel_strom_verbraucht_waschmaschine(engine, sensor_entities):
    result = engine.match("wie viel Strom verbraucht die Waschmaschine?", sensor_entities)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "1200 Watt."


def test_wie_viel_energie_verbraucht_waschmaschine(engine, sensor_entities):
    result = engine.match("wie viel Energie verbraucht die Waschmaschine Verbrauch?", sensor_entities)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "3.7 Kilowattstunden."


def test_wie_ist_fensterkontakt_buero_batterie_speaks_percentage(engine, sensor_entities):
    result = engine.match("wie ist die Fensterkontakt Büro Batterie?", sensor_entities)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "84 Prozent."

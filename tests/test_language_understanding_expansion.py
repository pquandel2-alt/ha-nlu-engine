"""Regression corpus for the broader, still deterministic German NLU."""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext
from ha_nlu.nlu.parse_outcome import ParseFailureReason


ENTITIES = [
    EntitySnapshot(
        "sensor.wohnzimmer_temp", "Wohnzimmer Temperatur", "sensor", "21.5",
        area_id="wohnzimmer", area_name="Wohnzimmer", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0, unit="°C", device_class="temperature",
    ),
    EntitySnapshot(
        "sensor.kueche_temp", "Küche Temperatur", "sensor", "22.5",
        area_id="kueche", area_name="Küche", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0, unit="°C", device_class="temperature",
    ),
    EntitySnapshot(
        "sensor.schlafzimmer_temp", "Schlafzimmer Temperatur", "sensor", "19",
        area_id="schlafzimmer", area_name="Schlafzimmer", floor_id="og",
        floor_name="Obergeschoss", floor_level=1, unit="°C", device_class="temperature",
    ),
    EntitySnapshot(
        "sensor.wohnzimmer_humidity", "Wohnzimmer Luftfeuchtigkeit", "sensor", "51",
        area_id="wohnzimmer", area_name="Wohnzimmer", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0, unit="%", device_class="humidity",
    ),
    EntitySnapshot(
        "sensor.kueche_energy", "Küche Energie", "sensor", "3.7",
        area_id="kueche", area_name="Küche", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0, unit="kWh", device_class="energy",
    ),
    EntitySnapshot(
        "sensor.upstairs_battery", "Fenster Batterie", "sensor", "12",
        area_id="schlafzimmer", area_name="Schlafzimmer", floor_id="og",
        floor_name="Obergeschoss", floor_level=1, unit="%", device_class="battery",
    ),
    EntitySnapshot(
        "cover.buero", "Rollladen Büro", "cover", "closed",
        area_id="buero", area_name="Büro", capabilities=frozenset({"POSITION"}),
    ),
    EntitySnapshot(
        "light.kueche", "Küchenlicht", "light", "off",
        area_id="kueche", area_name="Küche",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    ),
    EntitySnapshot(
        "climate.erdgeschoss", "Erdgeschoss Heizung", "climate", "heat",
        area_id="wohnzimmer", area_name="Wohnzimmer", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0,
        attributes={"temperature": 21}, capabilities=frozenset({"TEMPERATURE"}),
    ),
    EntitySnapshot(
        "fan.wohnzimmer", "Wohnzimmer Ventilator", "fan", "on",
        area_id="wohnzimmer", area_name="Wohnzimmer", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0,
        attributes={"percentage_step": 10.0},
        capabilities=frozenset({"FAN_SPEED"}),
    ),
]


def _context(result) -> ConversationContext:
    return ConversationContext(
        last_command=result.command,
        last_entities=tuple(result.command.entities),
        last_area=result.command.area,
        pending_clarification=None,
    )


def test_general_location_properties(engine):
    assert engine.match("Luftfeuchtigkeit im Wohnzimmer", ENTITIES).response_text == "51 Prozent."
    assert engine.match("Stromverbrauch Küche", ENTITIES).response_text == "3.7 Kilowattstunden."
    assert engine.match("Temperatur Obergeschoss", ENTITIES).response_text == "19 Grad."


def test_multiple_measurements_are_listed_and_average_is_opt_in(engine):
    listed = engine.match("Temperatur Erdgeschoss", ENTITIES)
    averaged = engine.match("durchschnittliche Temperatur im Erdgeschoss", ENTITIES)

    assert listed.response_text == "Küche Temperatur: 22,5 Grad; Wohnzimmer Temperatur: 21,5 Grad."
    assert averaged.response_text == "Der Durchschnitt für Temperatur beträgt 22 Grad."


def test_battery_threshold_on_floor(engine):
    result = engine.match("Batterien oben unter 20 Prozent", ENTITIES)
    assert result is not None
    assert result.command.entities[0].entity_id == "sensor.upstairs_battery"
    assert result.response_text == "12 Prozent."


def test_precise_location_failures(engine):
    assert engine.match("Temperatur im Partykeller", ENTITIES) is None
    assert engine.failure_feedback("Temperatur im Partykeller", ENTITIES) == (
        "Ich kenne keinen Raum und keine Etage namens Partykeller."
    )
    assert engine.failure_feedback("Luftfeuchtigkeit im Büro", ENTITIES) == (
        "Für Luftfeuchtigkeit ist in Büro kein passender Sensor für Assist freigegeben."
    )
    assert engine.understanding_feedback(
        "Temperatur im Partykeller", ENTITIES
    ).reason is ParseFailureReason.UNKNOWN_LOCATION


def test_query_correction_and_natural_floor_followup(engine):
    first = engine.match("Wie warm ist es im Wohnzimmer", ENTITIES)
    corrected = engine.match_query_followup("Nein, ich meinte Küche", ENTITIES, _context(first))
    upstairs = engine.match_query_followup("Wie sieht es oben aus?", ENTITIES, _context(first))

    assert corrected.response_text == "22.5 Grad."
    assert upstairs.response_text == "19 Grad."


def test_colloquial_device_alias_and_polite_stt_form(engine):
    cover = engine.match("Mach Rollo Büro auf", ENTITIES)
    light = engine.match("Könntest du Küchenlicht anmachen?", ENTITIES)

    assert cover.plan.entity_id == "cover.buero"
    assert light.plan.entity_id == "light.kueche"


def test_common_stt_token_splits_are_normalized(engine):
    cover = engine.match("Mach Roll Laden Büro auf", ENTITIES)
    light = engine.match("Könntest du Küchenlicht an machen?", ENTITIES)

    assert cover.plan.entity_id == "cover.buero"
    assert light.plan.entity_id == "light.kueche"


def test_natural_clock_phrases(engine):
    half = engine.match_calendar_time_automation(
        "Morgen halb acht schalte das Küchenlicht ein", ENTITIES
    )
    quarter = engine.match_calendar_time_automation(
        "Morgen viertel vor neun schalte das Küchenlicht ein", ENTITIES
    )
    weekday = engine.match_calendar_time_automation(
        "Nächsten Samstag um 10 Uhr schalte das Küchenlicht ein", ENTITIES
    )

    assert (half.model.calendar_schedule.hour, half.model.calendar_schedule.minute) == (7, 30)
    assert (quarter.model.calendar_schedule.hour, quarter.model.calendar_schedule.minute) == (8, 45)
    assert weekday.model.calendar_schedule.weekday == 5


def test_action_first_and_every_time_automation_without_comma(engine):
    window = EntitySnapshot(
        "binary_sensor.buero_fenster", "Bürofenster", "binary_sensor", "off",
        area_id="buero", area_name="Büro", device_class="window",
    )
    entities = ENTITIES + [window]

    action_first = engine.match_automation(
        "Schalte das Küchenlicht ein wenn das Bürofenster geöffnet wird", entities
    )
    recurring_wording = engine.match_automation(
        "Jedes Mal wenn das Bürofenster geöffnet wird schalte das Küchenlicht ein", entities
    )

    assert action_first is not None and action_first.validation_error is None
    assert recurring_wording is not None and recurring_wording.validation_error is None


def test_temperature_query_can_drive_contextual_setpoint(engine):
    query = engine.match("Wie hoch ist die Temperatur im Erdgeschoss?", ENTITIES)
    result = engine.match_contextual_property_followup(
        "Kannst du die Temperatur auf 22 Grad erhöhen?", ENTITIES, _context(query)
    )

    assert result is not None
    assert result.plan.domain == "climate"
    assert result.plan.service == "set_temperature"
    assert result.plan.entity_id == "climate.erdgeschoss"
    assert result.plan.data == {"temperature": 22}


def test_contextual_property_inference_covers_light_cover_and_fan(engine):
    light_query = engine.match("Wie hell ist es in der Küche?", ENTITIES)
    brightness = engine.match_contextual_property_followup(
        "Kannst du die Helligkeit auf 40 Prozent erhöhen?",
        ENTITIES,
        _context(light_query),
    )

    cover = next(entity for entity in ENTITIES if entity.entity_id == "cover.buero")
    cover_context = ConversationContext(
        last_command=None,
        last_entities=(cover,),
        last_area=None,
        pending_clarification=None,
    )
    position = engine.match_contextual_property_followup(
        "Kannst du die Position auf 60 Prozent stellen?", ENTITIES, cover_context
    )

    fan = next(entity for entity in ENTITIES if entity.entity_id == "fan.wohnzimmer")
    fan_context = ConversationContext(
        last_command=None,
        last_entities=(fan,),
        last_area=None,
        pending_clarification=None,
    )
    level = engine.match_contextual_property_followup(
        "Kannst du die Stufe auf drei stellen?", ENTITIES, fan_context
    )

    assert brightness.plan.service == "turn_on"
    assert brightness.plan.data == {"brightness_pct": 40}
    assert position.plan.service == "set_cover_position"
    assert position.plan.data == {"position": 60}
    assert level.plan.service == "turn_on"
    assert level.plan.data == {"percentage": 30}


def test_contextual_setpoint_clarifies_multiple_actuators_and_keeps_value(engine):
    second = EntitySnapshot(
        "climate.kueche", "Küche Heizung", "climate", "heat",
        area_id="kueche", area_name="Küche", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0,
        attributes={"temperature": 21}, capabilities=frozenset({"TEMPERATURE"}),
    )
    entities = ENTITIES + [second]
    query = engine.match("Wie hoch ist die Temperatur im Erdgeschoss?", entities)

    ambiguous = engine.match_contextual_property_followup(
        "Kannst du die Temperatur auf 22 Grad erhöhen?", entities, _context(query)
    )
    resolved = engine.resolve_clarification(
        "Küche Heizung", ambiguous.clarification, entities
    )

    assert ambiguous.response_text == "Welche Heizung meinst du?"
    assert resolved.plan.entity_id == "climate.kueche"
    assert resolved.plan.data == {"temperature": 22}


def test_read_only_measurement_never_implies_an_actuator(engine):
    battery = engine.match("Batterien oben unter 20 Prozent", ENTITIES)
    assert engine.match_contextual_property_followup(
        "Kannst du die Batterie auf 80 Prozent stellen?", ENTITIES, _context(battery)
    ) is None

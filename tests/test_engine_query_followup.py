"""HomeIntent plan V4.9, "Cross-Sentence References": a state query with no
entity name at all, only a room ("Wie warm ist es im Wohnzimmer?" - the
plan's own example, ``AreaQueryParser``/``area_query.yaml``), followed by a
same-shape follow-up that only names the *new* room or floor ("Und in der
Küche?"/"Und oben?" - ``QueryFollowupParser``/``query_followup.yaml`` plus
``NluEngine.match_query_followup()``). Domain/device_class are carried over
from the previous turn's ``ConversationContext``, never re-spoken.

Mirrors ``test_reference.py``'s end-to-end pattern: a real ``match()`` builds
the ``SemanticCommand`` that becomes the next turn's context, exactly how
``conversation.py`` chains ``match()`` -> context -> ``match_query_followup()``.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext

WOHNZIMMER_TEMP = EntitySnapshot(
    "sensor.wohnzimmer_temp", "Wohnzimmer Temperatur", "sensor", "21.5",
    area_id="wohnzimmer", area_name="Wohnzimmer", unit="°C", device_class="temperature",
)
WOHNZIMMER_TEMP_2 = EntitySnapshot(
    "sensor.wohnzimmer_temp_2", "Wohnzimmer Temperatur 2", "sensor", "21.0",
    area_id="wohnzimmer", area_name="Wohnzimmer", unit="°C", device_class="temperature",
)
KUECHE_TEMP = EntitySnapshot(
    "sensor.kueche_temp", "Küche Temperatur", "sensor", "23.0",
    area_id="kueche", area_name="Küche", floor_id="eg", floor_name="Erdgeschoss", floor_level=0,
    unit="°C", device_class="temperature",
)
OBEN_TEMP = EntitySnapshot(
    "sensor.schlafzimmer_temp", "Schlafzimmer Temperatur", "sensor", "19.0",
    area_id="schlafzimmer", area_name="Schlafzimmer", floor_id="og", floor_name="Obergeschoss", floor_level=1,
    unit="°C", device_class="temperature",
)
LAMP = EntitySnapshot(
    "light.wohnzimmerlampe", "Wohnzimmerlampe", "light", "on",
    area_id="wohnzimmer", area_name="Wohnzimmer", attributes={"brightness": 128},
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
KUECHE_SWITCH = EntitySnapshot(
    "switch.kueche_kaffeemaschine", "Kaffeemaschine", "switch", "off",
    area_id="kueche", area_name="Küche",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)

ENTITIES = [WOHNZIMMER_TEMP, KUECHE_TEMP, OBEN_TEMP, LAMP]


def _context(engine, text: str, entities: list[EntitySnapshot]) -> ConversationContext:
    """Real first-turn match(), context built the same way conversation.py does."""
    result = engine.match(text, entities)
    assert result is not None
    assert result.command is not None
    return ConversationContext(
        last_command=result.command,
        last_entities=tuple(result.command.entities),
        last_area=result.command.area,
        pending_clarification=None,
    )


def test_area_query_first_turn(engine):
    result = engine.match("wie warm ist es im Wohnzimmer", ENTITIES)
    assert result is not None
    assert result.command.intent == "HassGetState"
    assert result.command.entities[0].entity_id == "sensor.wohnzimmer_temp"
    assert result.response_text == "21.5 Grad."


def test_area_query_first_turn_variant_kalt(engine):
    # "[warm|kalt]" is decorative - either word (or omitting it) reaches the
    # same grammar and the same sensor.
    result = engine.match("wie kalt ist es im Wohnzimmer", ENTITIES)
    assert result is not None
    assert result.command.entities[0].entity_id == "sensor.wohnzimmer_temp"


def test_area_query_first_turn_returns_none_for_ambiguous_area(engine):
    entities = ENTITIES + [WOHNZIMMER_TEMP_2]
    assert engine.match("wie warm ist es im Wohnzimmer", entities) is None


def test_area_query_first_turn_returns_none_for_unresolvable_area(engine):
    assert engine.match("wie warm ist es im Partykeller", ENTITIES) is None


def test_query_followup_area(engine):
    context = _context(engine, "wie warm ist es im Wohnzimmer", ENTITIES)
    result = engine.match_query_followup("Und in der Küche?", ENTITIES, context)
    assert result is not None
    assert result.command.entities[0].entity_id == "sensor.kueche_temp"
    assert result.response_text == "23.0 Grad."


def test_query_followup_level(engine):
    context = _context(engine, "wie warm ist es im Wohnzimmer", ENTITIES)
    result = engine.match_query_followup("Und oben?", ENTITIES, context)
    assert result is not None
    assert result.command.entities[0].entity_id == "sensor.schlafzimmer_temp"
    assert result.response_text == "19.0 Grad."


def test_query_followup_level_unten_returns_none_without_matching_floor(engine):
    # No entity on floor_level 0 exists with a device_class among ENTITIES'
    # own sensors other than kueche (eg/level 0) - still, "unten" should
    # resolve to the eg floor and find the kueche sensor.
    context = _context(engine, "wie warm ist es im Wohnzimmer", ENTITIES)
    result = engine.match_query_followup("Und unten?", ENTITIES, context)
    assert result is not None
    assert result.command.entities[0].entity_id == "sensor.kueche_temp"


def test_query_followup_carries_over_light_domain_without_device_class(engine):
    context = _context(engine, "wie hell ist die Wohnzimmerlampe", ENTITIES)
    entities = ENTITIES + [
        EntitySnapshot(
            "light.kuechenlicht", "Küchenlicht", "light", "on",
            area_id="kueche", area_name="Küche", attributes={"brightness": 64},
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        ),
    ]
    result = engine.match_query_followup("Und in der Küche?", entities, context)
    assert result is not None
    assert result.command.entities[0].entity_id == "light.kuechenlicht"


def test_query_followup_returns_none_without_context(engine):
    assert engine.match_query_followup("Und oben?", ENTITIES, None) is None


def test_query_followup_returns_none_after_non_query_command_turn(engine):
    context = _context(engine, "Mach die Wohnzimmerlampe an", ENTITIES)
    assert engine.match_query_followup("Und in der Küche?", ENTITIES, context) is None


def test_query_followup_returns_none_for_unresolvable_area(engine):
    context = _context(engine, "wie warm ist es im Wohnzimmer", ENTITIES)
    assert engine.match_query_followup("Und im Partykeller?", ENTITIES, context) is None


def test_query_followup_returns_none_for_ambiguous_match_in_new_area(engine):
    entities = ENTITIES + [
        EntitySnapshot(
            "sensor.kueche_temp_2", "Küche Temperatur 2", "sensor", "22.0",
            area_id="kueche", area_name="Küche", unit="°C", device_class="temperature",
        ),
    ]
    context = _context(engine, "wie warm ist es im Wohnzimmer", entities)
    assert engine.match_query_followup("Und in der Küche?", entities, context) is None


def test_query_followup_returns_none_for_switch_domain_without_device_class(engine):
    # "Mach die Kaffeemaschine an" isn't a query turn at all, so this is
    # already covered by test_query_followup_returns_none_after_non_query_command_turn;
    # this case instead exercises a query-turn reference entity whose own
    # domain has no meaningful device_class to carry over (switches have
    # none) - refuse rather than guess what "Und oben?" would even mean.
    context = ConversationContext(
        last_command=_context(engine, "wie warm ist es im Wohnzimmer", ENTITIES).last_command,
        last_entities=(KUECHE_SWITCH,),
        last_area=None,
        pending_clarification=None,
    )
    assert engine.match_query_followup("Und oben?", ENTITIES + [KUECHE_SWITCH], context) is None

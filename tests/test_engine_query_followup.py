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

from ha_nlu.devices import DeviceSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext
from ha_nlu.world_model import build_world_model

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


def _context_with_world_model(engine, text: str, entities: list[EntitySnapshot], world_model) -> ConversationContext:
    """Same as ``_context`` but threads a WorldModel through the first-turn
    ``match()`` too - required for HassDeviceQuery, which only resolves with
    one (see ``_parse_device_query``)."""
    result = engine.match(text, entities, world_model)
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


# --- Phase 8 (HomeIntent v4.2.1 plan): state-query follow-ups -------------
#
# "Und im Bad?" etc. after a HassStateQuery/HassCheckState/HassExistsQuery
# turn - continues using the previous turn's QueryCommand
# (frame.parameters["query_command"], Phase 7) rather than last_entities[0],
# so domain/device_class/filter.state/scope all carry over exactly, only
# the area changes. Mirrors the HassGetState tests above in style.

FENSTER_KELLER = EntitySnapshot(
    "binary_sensor.fenster_keller", "Fenster Keller", "binary_sensor", "on",
    area_id="keller", area_name="Keller", device_class="window",
)
FENSTER_BAD = EntitySnapshot(
    "binary_sensor.fenster_bad", "Fenster Bad", "binary_sensor", "off",
    area_id="bad", area_name="Bad", device_class="window",
)
FENSTER_BAD_2 = EntitySnapshot(
    "binary_sensor.fenster_bad_2", "Fenster Bad 2", "binary_sensor", "on",
    area_id="bad", area_name="Bad", device_class="window",
)
FENSTER_BUERO = EntitySnapshot(
    "binary_sensor.fenster_buero", "Fenster Büro", "binary_sensor", "on",
    area_id="buero", area_name="Büro", device_class="window",
)

STATE_QUERY_ENTITIES = [FENSTER_KELLER, FENSTER_BAD]


def test_query_followup_continues_state_query_list(engine):
    context = _context(engine, "welche Fenster sind offen", STATE_QUERY_ENTITIES)
    assert context.last_command.entities == (FENSTER_KELLER,)
    result = engine.match_query_followup("Und im Bad?", STATE_QUERY_ENTITIES, context)
    assert result is not None
    assert result.command.intent == "HassStateQuery"
    # FENSTER_BAD is closed - the new area legitimately has zero open
    # windows, a normal EMPTY answer, not a "not understood" miss.
    assert result.command.entities == ()
    assert result.response_text == "Es sind keine Fenster geöffnet."


def test_query_followup_continues_state_query_list_with_a_match(engine):
    context = _context(engine, "welche Fenster sind offen", STATE_QUERY_ENTITIES)
    result = engine.match_query_followup("Und im Büro?", STATE_QUERY_ENTITIES + [FENSTER_BUERO], context)
    assert result is not None
    assert result.command.entities == (FENSTER_BUERO,)
    assert result.response_text == "Fenster Büro ist geöffnet."


def test_query_followup_continues_state_query_count_scope(engine):
    context = _context(engine, "wie viele Fenster sind offen", STATE_QUERY_ENTITIES)
    result = engine.match_query_followup(
        "Und im Bad?", STATE_QUERY_ENTITIES + [FENSTER_BAD_2], context
    )
    assert result is not None
    # count_only must carry over too, not just the entity set.
    assert result.command.entities == (FENSTER_BAD_2,)
    assert result.response_text == "Fenster Bad 2 ist geöffnet."


def test_query_followup_continues_exists_query(engine):
    context = _context(engine, "gibt es offene Fenster", STATE_QUERY_ENTITIES)
    result = engine.match_query_followup("Und im Bad?", STATE_QUERY_ENTITIES, context)
    assert result is not None
    assert result.command.intent == "HassExistsQuery"
    assert result.command.entities == ()
    assert result.response_text == "Nein, es gibt keine Fenster."


def test_query_followup_continues_check_state(engine):
    context = _context(engine, "ist das Fenster Keller offen", STATE_QUERY_ENTITIES)
    assert context.last_command.intent == "HassCheckState"
    result = engine.match_query_followup("Und im Bad?", STATE_QUERY_ENTITIES, context)
    assert result is not None
    assert result.command.intent == "HassCheckState"
    assert result.command.entities == (FENSTER_BAD,)
    assert result.response_text == "Nein, Fenster Bad ist nicht geöffnet."


def test_query_followup_check_state_returns_none_for_ambiguous_new_area(engine):
    context = _context(engine, "ist das Fenster Keller offen", STATE_QUERY_ENTITIES)
    entities = STATE_QUERY_ENTITIES + [FENSTER_BAD_2]
    result = engine.match_query_followup("Und im Bad?", entities, context)
    assert result is None  # two windows in Bad now - never guess which one


def test_query_followup_check_state_returns_none_for_no_match_in_new_area(engine):
    context = _context(engine, "ist das Fenster Keller offen", STATE_QUERY_ENTITIES)
    result = engine.match_query_followup("Und im Büro?", STATE_QUERY_ENTITIES, context)
    assert result is None  # no window in Büro at all - TARGET_NOT_FOUND, never guess


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


# --- Phase 3 (follow-up wave): HassDeviceQuery follow-ups -------------------
#
# "Welche Geräte sind im Büro?" -> "Und im Keller?" - devices come from the
# WorldModel (cross-domain, no domain/device_class to carry over like the
# ENTITY-scope followups above), so this must re-scope by area only, not
# fall back to an unfiltered entity list (the bug this phase actually fixes -
# see _parse_state_query_followup's QueryTargetKind.DEVICE branch).

SCHREIBTISCHLAMPE_BUERO = EntitySnapshot(
    "light.schreibtischlampe", "Schreibtischlampe", "light", "on",
    area_id="buero", area_name="Büro",
)
DRUCKER_KELLER = EntitySnapshot(
    "switch.drucker", "Drucker", "switch", "off",
    area_id="keller", area_name="Keller",
)
# Bad has an entity (so the area itself resolves, unlike "Bunker" - see
# StateQueryParser's own unknown-area precedent) but no DeviceSnapshot -
# devices_in_area() legitimately returns none, exercising the EMPTY branch.
FENSTER_BAD_UNDEVICED = EntitySnapshot(
    "binary_sensor.fenster_bad", "Fenster Bad", "binary_sensor", "off",
    area_id="bad", area_name="Bad", device_class="window",
)
DEVICE_QUERY_ENTITIES = [SCHREIBTISCHLAMPE_BUERO, DRUCKER_KELLER, FENSTER_BAD_UNDEVICED]


def _device_query_world_model():
    devices = [
        DeviceSnapshot(
            device_id="device.schreibtischlampe", name="Schreibtischlampe",
            area_id="buero", area_name="Büro", entity_ids=("light.schreibtischlampe",),
        ),
        DeviceSnapshot(
            device_id="device.drucker", name="Drucker",
            area_id="keller", area_name="Keller", entity_ids=("switch.drucker",),
        ),
    ]
    return build_world_model(DEVICE_QUERY_ENTITIES, devices)


def test_query_followup_continues_device_query_in_new_area(engine):
    world_model = _device_query_world_model()
    context = _context_with_world_model(engine, "welche Geräte sind im Büro", DEVICE_QUERY_ENTITIES, world_model)
    assert context.last_command.intent == "HassDeviceQuery"
    result = engine.match_query_followup("Und im Keller?", DEVICE_QUERY_ENTITIES, context, world_model)
    assert result is not None
    assert result.command.intent == "HassDeviceQuery"
    assert result.response_text == "Drucker ist im Keller."


def test_query_followup_device_query_empty_area_is_a_normal_answer(engine):
    world_model = _device_query_world_model()
    context = _context_with_world_model(engine, "welche Geräte sind im Büro", DEVICE_QUERY_ENTITIES, world_model)
    result = engine.match_query_followup("Und im Bad?", DEVICE_QUERY_ENTITIES, context, world_model)
    assert result is not None  # Bad is a known area, just with no devices - EMPTY, not a miss
    assert result.response_text == "Im Bad sind keine Geräte bekannt."


def test_query_followup_device_query_floor_only_returns_none(engine):
    # QueryTarget(kind=DEVICE) has no floor field (same gap ReasoningEngine's
    # own Constraints building has) - "Und oben?" has nothing to resolve
    # against, so this refuses rather than guessing an area.
    world_model = _device_query_world_model()
    context = _context_with_world_model(engine, "welche Geräte sind im Büro", DEVICE_QUERY_ENTITIES, world_model)
    result = engine.match_query_followup("Und oben?", DEVICE_QUERY_ENTITIES, context, world_model)
    assert result is None

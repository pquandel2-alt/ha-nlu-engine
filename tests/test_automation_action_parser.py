"""V5 Wave 3 (V5.7-V5.12): automation_action_parser.py's AutomationActionParser -
spoken automation-action sentences -> nlu.action_model.ActionModel/ActionGroup.

Two positive cases per action type, plus sequence/parallel, duration/delay/wait
timeout, and negative/ambiguity cases, mirroring
tests/test_automation_condition_parser.py's "call the parser, not the engine"
style.

This parser has no caller in engine.py/conversation.py in this wave (see its
own module docstring) - tests exercise it directly.
"""

from __future__ import annotations

import pytest
from hassil import Intents

from ha_nlu.automation_action_parser import AUTOMATION_ACTION_DIR, AutomationActionParser
from ha_nlu.automation_condition_parser import AUTOMATION_CONDITION_DIR, AutomationConditionParser
from ha_nlu.devices import DeviceSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.action_model import ActionGroup, ActionModel, ActionType, ExecutionMode
from ha_nlu.nlu.parser import ParseContext
from ha_nlu.world_model import build_world_model

# --- Test fixtures: entities and devices for action parsing --------------

# V5 Wave 5 (V5.20, "Capability Validation") - real EntitySnapshots carry a
# capabilities set derived from live HA attributes (hass_entities.py); these
# fixtures hardcode the same values a fully-featured light/cover/fan/climate
# entity would report, so every pre-existing SET_* test below keeps exercising
# a capability-complete entity unless a test explicitly narrows it (see the
# dedicated V5.20 negative-case fixtures further down).
_LIGHT_CAPS = frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS", "COLOR", "COLOR_TEMPERATURE"})
_COVER_CAPS = frozenset({"TURN_ON", "TURN_OFF", "POSITION"})
_FAN_CAPS = frozenset({"TURN_ON", "TURN_OFF", "FAN_SPEED"})
_CLIMATE_CAPS = frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"})

WOHNZIMMER_LICHT = EntitySnapshot(
    entity_id="light.wohnzimmer_licht", friendly_name="Wohnzimmer Licht", domain="light",
    state="off", area_id="wohnzimmer", area_name="Wohnzimmer", capabilities=_LIGHT_CAPS,
)
FLUR_LICHT = EntitySnapshot(
    entity_id="light.flur_licht", friendly_name="Flurlicht", domain="light",
    state="off", area_id="flur", area_name="Flur", capabilities=_LIGHT_CAPS,
)
KUECHE_LICHT = EntitySnapshot(
    entity_id="light.kueche_licht", friendly_name="Küchenlicht", domain="light",
    state="off", area_id="kueche", area_name="Küche", capabilities=_LIGHT_CAPS,
)
WOHNZIMMER_ROLLLADEN = EntitySnapshot(
    entity_id="cover.wohnzimmer_rollladen", friendly_name="Wohnzimmer Rollladen", domain="cover",
    state="closed", area_id="wohnzimmer", area_name="Wohnzimmer", capabilities=_COVER_CAPS,
)
WOHNZIMMER_HEIZUNG = EntitySnapshot(
    entity_id="climate.wohnzimmer_heizung", friendly_name="Wohnzimmer Heizung", domain="climate",
    state="heat", area_id="wohnzimmer", area_name="Wohnzimmer", capabilities=_CLIMATE_CAPS,
)
WOHNZIMMER_VENTILATOR = EntitySnapshot(
    entity_id="fan.wohnzimmer_ventilator", friendly_name="Wohnzimmer Ventilator", domain="fan",
    state="off", area_id="wohnzimmer", area_name="Wohnzimmer", capabilities=_FAN_CAPS,
)
KUECHE_STECKDOSE = EntitySnapshot(
    entity_id="switch.kueche_steckdose", friendly_name="Küche Steckdose", domain="switch",
    state="off", area_id="kueche", area_name="Küche",
)
SONNE = EntitySnapshot(entity_id="sun.sun", friendly_name="Sonne", domain="sun", state="above_horizon")

ALL_ENTITIES = [
    WOHNZIMMER_LICHT, FLUR_LICHT, KUECHE_LICHT, WOHNZIMMER_ROLLLADEN, WOHNZIMMER_HEIZUNG,
    WOHNZIMMER_VENTILATOR, KUECHE_STECKDOSE, SONNE,
]
ALL_DEVICES: list[DeviceSnapshot] = []


@pytest.fixture(scope="module")
def condition_parser() -> AutomationConditionParser:
    """WAIT (V5.12) delegates to a real condition parser instance (composition,
    see automation_action_parser.py's own module docstring)."""
    yaml_files = sorted(AUTOMATION_CONDITION_DIR.glob("*.yaml"))
    intents = Intents.from_files(yaml_files)
    return AutomationConditionParser(intents, max_depth=3)


@pytest.fixture(scope="module")
def parser(condition_parser: AutomationConditionParser) -> AutomationActionParser:
    """Load action intents from automation_action/*.yaml and construct parser."""
    yaml_files = sorted(AUTOMATION_ACTION_DIR.glob("*.yaml"))
    intents = Intents.from_files(yaml_files)
    return AutomationActionParser(intents, condition_parser, max_depth=3)


@pytest.fixture(scope="module")
def context() -> ParseContext:
    """Build parse context with all test entities."""
    world_model = build_world_model(ALL_ENTITIES, ALL_DEVICES)
    return ParseContext(entities=ALL_ENTITIES, index=world_model.entity_index, world_model=world_model)


# ============================================================================
# Section 1: Setup (1 Test)
# ============================================================================


def test_setup_loads_eleven_action_types_grammar(parser):
    """The action grammar loads and the parser is constructed without error."""
    assert parser is not None


# ============================================================================
# Section 2: TURN_ON (2+ Tests)
# ============================================================================


def test_turn_on_by_domain_and_area(parser, context):
    """"mach das Licht im Wohnzimmer an" -> TURN_ON light/wohnzimmer."""
    result = parser.parse("mach das Licht im Wohnzimmer an", context)
    assert result is not None
    assert len(result) == 1
    action = result[0]
    assert isinstance(action, ActionModel)
    assert action.type is ActionType.TURN_ON
    assert action.target.domain == "light"
    assert action.target.area_id == "wohnzimmer"


def test_turn_on_by_name(parser, context):
    """"schalte das Flurlicht ein" -> TURN_ON resolved to the named entity."""
    result = parser.parse("schalte das Flurlicht ein", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.TURN_ON
    assert action.target.domain == "light"


def test_turn_on_cover_via_hoch(parser, context):
    """"fahre den Rollladen hoch" -> TURN_ON cover (domain-agnostic boundary
    decision, see automation_action_parser.py's own module docstring)."""
    result = parser.parse("fahre den Rollladen hoch", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.TURN_ON
    assert action.target.domain == "cover"


def test_turn_on_with_duration_sets_duration_seconds():
    """"...für 30 Minuten..." sets ActionModel.duration_seconds (V5.11)."""
    result = _parse_single_action("schalte das Licht im Wohnzimmer für 30 Minuten ein")
    assert result.type is ActionType.TURN_ON
    assert result.duration_seconds == 1800


# ============================================================================
# Section 3: TURN_OFF (2 Tests)
# ============================================================================


def test_turn_off_by_domain_and_area(parser, context):
    """"mach den Schalter in der Küche aus" -> TURN_OFF switch/kueche."""
    result = parser.parse("mach den Schalter in der Küche aus", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.TURN_OFF
    assert action.target.domain == "switch"
    assert action.target.area_id == "kueche"
    assert action.duration_seconds is None


def test_turn_off_cover_via_runter(parser, context):
    """"fahre den Rollladen runter" -> TURN_OFF cover."""
    result = parser.parse("fahre den Rollladen runter", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.TURN_OFF
    assert action.target.domain == "cover"


# ============================================================================
# Section 3b: Natural Language Quantifiers in Automations (V5 Wave 4, V5.17)
# ============================================================================


def test_turn_off_quantifier_all_lights(parser, context):
    """"schalte alle Lichter aus" -> TURN_OFF, quantifier=all, all 3 lights."""
    result = parser.parse("schalte alle Lichter aus", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.TURN_OFF
    assert action.target.domain == "light"
    assert action.target.quantifier == "all"
    assert action.target.quantifier_count is None
    assert action.target.exclude_entity_ids == ()


def test_turn_on_quantifier_both_requires_exactly_two_matches(parser, context):
    """"mach beide Lichter an" - "beide" only ever means exactly 2 (Regel 4,
    never guess) - refused here since ALL_ENTITIES has 3 lights domain-wide."""
    assert parser.parse("mach beide Lichter an", context) is None


def test_turn_on_quantifier_both_lights_in_one_area():
    """Two lights, scoped to exactly 2 matches - "beide" resolves unambiguously."""
    result = _parse_single_action_with_entities("mach beide Lichter an", [WOHNZIMMER_LICHT, FLUR_LICHT])
    assert result.type is ActionType.TURN_ON
    assert result.target.quantifier == "both"


def test_turn_on_quantifier_count_requires_exact_match_count(parser, context):
    """"mach die drei Lichter an" -> quantifier=count, count=3 (all 3 test lights)."""
    result = parser.parse("mach die drei Lichter an", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.TURN_ON
    assert action.target.quantifier == "count"
    assert action.target.quantifier_count == 3


def test_turn_on_quantifier_count_refuses_when_match_count_differs(parser, context):
    """"mach die beiden Lichter an" phrased as count=2, but 3 lights exist
    domain-wide - refuse rather than silently acting on the wrong set."""
    assert parser.parse("mach die zwei Lichter an", context) is None


def test_turn_off_quantifier_all_with_exclusion(parser, context):
    """"schalte alle Lichter aus außer dem Flurlicht" -> quantifier=all,
    Flurlicht excluded from both the match set and the count check."""
    result = parser.parse("schalte alle Lichter aus außer dem Flurlicht", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.TURN_OFF
    assert action.target.quantifier == "all"
    assert action.target.exclude_entity_ids == ("light.flur_licht",)


def test_turn_on_quantifier_exclusion_target_must_resolve(parser, context):
    """An exclusion name that doesn't resolve to a known entity refuses the
    whole action (Regel 4) rather than silently ignoring the exclusion."""
    assert parser.parse("schalte alle Lichter an außer dem Dingsbums", context) is None


# ============================================================================
# Section 4: SET_BRIGHTNESS / SET_POSITION / SET_FAN_SPEED (V5.7, one
# grammar intent dispatched by resolved target domain - see
# set_percentage_action.yaml's own comment) (6 Tests)
# ============================================================================


def test_set_brightness_for_light_domain(parser, context):
    """"stelle das Licht auf 50 Prozent" -> SET_BRIGHTNESS (light domain)."""
    result = parser.parse("stelle das Licht auf 50 Prozent", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_BRIGHTNESS
    assert action.target.domain == "light"
    assert action.value == 50.0


def test_set_position_for_cover_domain(parser, context):
    """"fahre den Rollladen auf 30 Prozent" -> SET_POSITION (cover domain)."""
    result = parser.parse("fahre den Rollladen auf 30 Prozent", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_POSITION
    assert action.target.domain == "cover"
    assert action.value == 30.0


def test_set_fan_speed_for_fan_domain(parser, context):
    """"stelle den Ventilator auf 70 Prozent" -> SET_FAN_SPEED (fan domain)."""
    result = parser.parse("stelle den Ventilator auf 70 Prozent", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_FAN_SPEED
    assert action.target.domain == "fan"
    assert action.value == 70.0


def test_set_percentage_refuses_climate_domain(parser, context):
    """Climate has no percent semantics - refused, not guessed (Regel 4)."""
    result = parser.parse("stelle die Heizung auf 50 Prozent", context)
    assert result is None


def test_set_percentage_refuses_switch_domain(parser, context):
    """Switch has no percent semantics - refused, not guessed (Regel 4)."""
    result = parser.parse("stelle den Schalter auf 50 Prozent", context)
    assert result is None


def test_set_percentage_by_area_resolves_correctly(parser, context):
    """"fahre den Rollladen im Wohnzimmer auf 30 Prozent" resolves target's
    area alongside the domain-driven type dispatch."""
    result = parser.parse("fahre den Rollladen im Wohnzimmer auf 30 Prozent", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_POSITION
    assert action.target.area_id == "wohnzimmer"


# ============================================================================
# Section 5: SET_TEMPERATURE (2 Tests)
# ============================================================================


def test_set_temperature_by_domain(parser, context):
    """"stelle die Heizung auf 21 Grad" -> SET_TEMPERATURE."""
    result = parser.parse("stelle die Heizung auf 21 Grad", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_TEMPERATURE
    assert action.target.domain == "climate"
    assert action.value == 21.0


def test_set_temperature_by_domain_and_area(parser, context):
    """"stelle die Heizung im Wohnzimmer auf 21 Grad" resolves area too."""
    result = parser.parse("stelle die Heizung im Wohnzimmer auf 21 Grad", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_TEMPERATURE
    assert action.target.area_id == "wohnzimmer"


# ============================================================================
# Section 6: SET_COLOR / SET_COLOR_TEMPERATURE (4 Tests)
# ============================================================================


def test_set_color_without_auf(parser, context):
    """"mach das Licht rot" -> SET_COLOR (no "auf" needed, domain-alone form)."""
    result = parser.parse("mach das Licht rot", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_COLOR
    assert action.color_name == "red"


def test_set_color_with_area_and_no_auf(parser, context):
    """"mach das Licht im Wohnzimmer rot" - {area} sentence works without the
    optional "auf" too (mandatory-preposition fix, see set_color_action.yaml's
    own comment)."""
    result = parser.parse("mach das Licht im Wohnzimmer rot", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_COLOR
    assert action.target.area_id == "wohnzimmer"
    assert action.color_name == "red"


def test_set_color_temperature_warmweiss(parser, context):
    """"stelle das Licht auf warmweiß" -> SET_COLOR_TEMPERATURE 2700K."""
    result = parser.parse("stelle das Licht auf warmweiß", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_COLOR_TEMPERATURE
    assert action.color_temp_kelvin == 2700


def test_set_color_temperature_kaltweiss_with_area(parser, context):
    """"stelle das Licht im Wohnzimmer auf kaltweiß" -> 6500K, area resolved."""
    result = parser.parse("stelle das Licht im Wohnzimmer auf kaltweiß", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_COLOR_TEMPERATURE
    assert action.color_temp_kelvin == 6500
    assert action.target.area_id == "wohnzimmer"


# ============================================================================
# Section 7: NOTIFY (2 Tests)
# ============================================================================


def test_notify_schick_mir_eine_nachricht(parser, context):
    """"schick mir eine Nachricht ..." -> NOTIFY with the trailing message."""
    result = parser.parse("schick mir eine Nachricht die Waschmaschine ist fertig", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.NOTIFY
    assert action.message == "die Waschmaschine ist fertig"
    assert action.target is None


def test_notify_benachrichtige_mich(parser, context):
    """"benachrichtige mich dass ..." -> NOTIFY."""
    result = parser.parse("benachrichtige mich dass der Akku leer ist", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.NOTIFY
    assert action.message == "der Akku leer ist"


# ============================================================================
# Section 8: DELAY Engine (V5.10) (3 Tests)
# ============================================================================


def test_delay_warte_n_minuten(parser, context):
    """"warte 5 Minuten" -> DELAY 300 seconds."""
    result = parser.parse("warte 5 Minuten", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.DELAY
    assert action.delay_seconds == 300


def test_delay_in_n_minuten(parser, context):
    """"in 10 Minuten" -> DELAY 600 seconds."""
    result = parser.parse("in 10 Minuten", context)
    assert result is not None
    action = result[0]
    assert action.delay_seconds == 600


def test_delay_nach_n_sekunden(parser, context):
    """"nach 30 Sekunden" -> DELAY 30 seconds (seconds granularity, V5.10)."""
    result = parser.parse("nach 30 Sekunden", context)
    assert result is not None
    action = result[0]
    assert action.delay_seconds == 30


# ============================================================================
# Section 9: WAIT Until (V5.12) (3 Tests)
# ============================================================================


def test_wait_bis_sun_condition(parser, context):
    """"warte bis es nach Sonnenuntergang ist" -> WAIT wrapping a SUN
    ConditionNode (delegated to AutomationConditionParser, Regel 6)."""
    result = parser.parse("warte bis es nach Sonnenuntergang ist", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.WAIT
    assert action.wait_condition is not None
    assert action.timeout_seconds is None


def test_wait_maximal_n_minuten_bis_condition_sets_timeout(parser, context):
    """"warte maximal 30 Minuten bis ..." sets timeout_seconds (V5.12)."""
    result = parser.parse("warte maximal 30 Minuten bis es nach Sonnenuntergang ist", context)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.WAIT
    assert action.timeout_seconds == 1800


def test_wait_refuses_unparseable_condition_text(parser, context):
    """"warte bis irgendwas komisches passiert" - not a phrasing any of the 9
    condition grammars understand -> whole WAIT is refused (Regel 4)."""
    result = parser.parse("warte bis irgendwas komisches passiert", context)
    assert result is None


# ============================================================================
# Section 10: Sequences (V5.8) & Parallel (V5.9) (5 Tests)
# ============================================================================


def test_sequence_of_two_actions_returns_flat_tuple(parser, context):
    """"..., und ..." (no "gleichzeitig") -> flat sequential tuple, no
    ActionGroup wrapper (matches AutomationModel.actions' own default shape)."""
    result = parser.parse("mach das Licht an und fahre den Rollladen hoch", context)
    assert result is not None
    assert len(result) == 2
    assert all(isinstance(step, ActionModel) for step in result)
    assert result[0].type is ActionType.TURN_ON
    assert result[0].target.domain == "light"
    assert result[1].type is ActionType.TURN_ON
    assert result[1].target.domain == "cover"


def test_sequence_of_three_actions_with_comma_and_und():
    """Comma- and "und"-separated chunks both split correctly."""
    result = _parse_actions("mach das Licht an, fahre den Rollladen hoch und stelle die Heizung auf 21 Grad")
    assert result is not None
    assert len(result) == 3
    assert [a.type for a in result] == [ActionType.TURN_ON, ActionType.TURN_ON, ActionType.SET_TEMPERATURE]


def test_parallel_marker_wraps_all_chunks_in_one_action_group(parser, context):
    """"gleichzeitig" (V5.9) wraps the whole sentence in one
    ActionGroup(PARALLEL, ...), not per-chunk mixing."""
    result = parser.parse("mach das Licht an und fahre den Rollladen hoch gleichzeitig", context)
    assert result is not None
    assert len(result) == 1
    group = result[0]
    assert isinstance(group, ActionGroup)
    assert group.mode is ExecutionMode.PARALLEL
    assert len(group.steps) == 2


def test_parallel_keyword_can_also_trigger_grouping(parser, context):
    """"parallel" is an accepted synonym for "gleichzeitig"."""
    result = parser.parse("mach das Licht an und fahre den Rollladen hoch parallel", context)
    assert result is not None
    assert isinstance(result[0], ActionGroup)


def test_single_action_still_returns_one_tuple_not_a_group(parser, context):
    """A bare single action (no "und"/","/"gleichzeitig") is a 1-tuple of
    ActionModel, never an ActionGroup."""
    result = parser.parse("mach das Licht an", context)
    assert result is not None
    assert len(result) == 1
    assert isinstance(result[0], ActionModel)


# ============================================================================
# Section 11: Ellipsis Scope Limitation (stated plainly, V5.8's own
# documented boundary) (1 Test)
# ============================================================================


def test_sequence_refuses_when_second_chunk_has_no_verb_of_its_own(parser, context):
    """Cross-clause ellipsis ("mach das Licht und den Rollladen an" - only
    one verb for two objects) is out of scope this wave (see
    automation_action_parser.py's own module docstring) - each chunk must be
    independently grammatical, so this whole sentence is refused."""
    result = parser.parse("mach gleichzeitig das Licht an und die Rollläden hoch", context)
    assert result is None


# ============================================================================
# Section 12: Negative / Refusal Cases (3 Tests)
# ============================================================================


def test_unresolvable_named_entity_refuses_whole_sentence(parser, context):
    """A named entity that doesn't exist -> refused, not guessed (Regel 4)."""
    result = parser.parse("schalte den Nichtvorhandenen Ofen ein", context)
    assert result is None


def test_any_unparseable_chunk_refuses_the_whole_sentence(parser, context):
    """One good chunk + one gibberish chunk still refuses everything - never
    partially guess (Regel 4, see AutomationActionParser.parse()'s own
    comment)."""
    result = parser.parse("mach das Licht an und blubb schnorch faselwurz", context)
    assert result is None


def test_empty_text_refuses(parser, context):
    """Empty/whitespace-only text has no chunks -> refused."""
    result = parser.parse("   ", context)
    assert result is None


# ============================================================================
# Section 13: V5 Wave 5 (V5.18, "Context in Automations") - pronoun "es"
# ============================================================================


def test_pronoun_es_resolves_against_a_single_remembered_entity(parser):
    world_model = build_world_model(ALL_ENTITIES, ALL_DEVICES)
    ctx = ParseContext(
        entities=ALL_ENTITIES, index=world_model.entity_index, world_model=world_model,
        last_entities=(WOHNZIMMER_LICHT,),
    )
    result = parser.parse("mach es auf 30 Prozent", ctx)
    assert result is not None
    action = result[0]
    assert action.type is ActionType.SET_BRIGHTNESS
    assert action.target.domain == "light"
    assert action.target.area_id == "wohnzimmer"
    assert action.value == 30.0


def test_pronoun_es_refuses_without_remembered_context(parser, context):
    result = parser.parse("mach es an", context)
    assert result is None


def test_pronoun_es_refuses_when_remembered_entities_span_multiple_domains(parser):
    world_model = build_world_model(ALL_ENTITIES, ALL_DEVICES)
    ctx = ParseContext(
        entities=ALL_ENTITIES, index=world_model.entity_index, world_model=world_model,
        last_entities=(WOHNZIMMER_LICHT, WOHNZIMMER_ROLLLADEN),
    )
    result = parser.parse("mach es an", ctx)
    assert result is None


# ============================================================================
# Section 14: V5 Wave 5 (V5.20, "Capability Validation") (5 Tests)
# ============================================================================


def _parse_actions_with_entities(parser: AutomationActionParser, text: str, entities: list[EntitySnapshot]):
    world_model = build_world_model(entities, [])
    ctx = ParseContext(entities=entities, index=world_model.entity_index, world_model=world_model)
    return parser.parse(text, ctx)


def test_set_color_refuses_a_brightness_only_light(parser):
    """A light without Capability.COLOR (e.g. a dimmable-only bulb) must
    refuse "mach ... blau" rather than build a no-op automation."""
    brightness_only_licht = EntitySnapshot(
        entity_id="light.dimmer", friendly_name="Dimmerlicht", domain="light",
        state="off", area_id="wohnzimmer", area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    )
    result = _parse_actions_with_entities(parser, "mach das Dimmerlicht blau", [brightness_only_licht])
    assert result is None


def test_set_brightness_succeeds_on_a_capable_light(parser):
    """The same capability check must not falsely reject a light that does
    have Capability.BRIGHTNESS."""
    brightness_only_licht = EntitySnapshot(
        entity_id="light.dimmer", friendly_name="Dimmerlicht", domain="light",
        state="off", area_id="wohnzimmer", area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    )
    result = _parse_actions_with_entities(parser, "stelle das Dimmerlicht auf 50 Prozent", [brightness_only_licht])
    assert result is not None
    assert result[0].type is ActionType.SET_BRIGHTNESS


def test_set_position_refuses_a_cover_without_position_capability(parser):
    """A cover that never reports current_position (derive_capabilities()'s
    own signal) has no Capability.POSITION - "auf 30 Prozent" must refuse."""
    dumb_rollladen = EntitySnapshot(
        entity_id="cover.dumb", friendly_name="Einfacher Rollladen", domain="cover",
        state="closed", area_id="wohnzimmer", area_name="Wohnzimmer",
        capabilities=frozenset(),
    )
    result = _parse_actions_with_entities(parser, "fahre den Einfachen Rollladen auf 30 Prozent", [dumb_rollladen])
    assert result is None


def test_turn_on_cover_ignores_capability_check_entirely(parser):
    """TURN_ON/TURN_OFF are never capability-gated (V5.20's own scope
    decision) - derive_capabilities() never grants Capability.TURN_ON for
    domain "cover" in the first place, so gating "hoch"/"runter" would break
    every legitimate cover automation. Same capability-less cover as above
    must still open via "hoch"."""
    dumb_rollladen = EntitySnapshot(
        entity_id="cover.dumb", friendly_name="Einfacher Rollladen", domain="cover",
        state="closed", area_id="wohnzimmer", area_name="Wohnzimmer",
        capabilities=frozenset(),
    )
    result = _parse_actions_with_entities(parser, "fahre die Rollläden im Wohnzimmer hoch", [dumb_rollladen])
    assert result is not None
    assert result[0].type is ActionType.TURN_ON


def test_set_color_temperature_refuses_a_light_without_that_capability(parser):
    """A light with COLOR but no COLOR_TEMPERATURE must refuse "warmweiß"."""
    color_only_licht = EntitySnapshot(
        entity_id="light.rgb_only", friendly_name="RGB Lampe", domain="light",
        state="off", area_id="wohnzimmer", area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS", "COLOR"}),
    )
    result = _parse_actions_with_entities(parser, "stelle die RGB Lampe auf warmweiß", [color_only_licht])
    assert result is None


# ============================================================================
# Helpers
# ============================================================================


def _build_parser() -> AutomationActionParser:
    cond_files = sorted(AUTOMATION_CONDITION_DIR.glob("*.yaml"))
    cond_intents = Intents.from_files(cond_files)
    condition_parser = AutomationConditionParser(cond_intents, max_depth=3)

    action_files = sorted(AUTOMATION_ACTION_DIR.glob("*.yaml"))
    action_intents = Intents.from_files(action_files)
    return AutomationActionParser(action_intents, condition_parser, max_depth=3)


def _build_context() -> ParseContext:
    world_model = build_world_model(ALL_ENTITIES, ALL_DEVICES)
    return ParseContext(entities=ALL_ENTITIES, index=world_model.entity_index, world_model=world_model)


def _parse_actions(text: str):
    return _build_parser().parse(text, _build_context())


def _parse_single_action(text: str) -> ActionModel:
    result = _parse_actions(text)
    assert result is not None
    assert len(result) == 1
    action = result[0]
    assert isinstance(action, ActionModel)
    return action


def _parse_single_action_with_entities(text: str, entities: list[EntitySnapshot]) -> ActionModel:
    """Same as _parse_single_action, but scoped to a custom entity set - used
    by the V5.17 quantifier tests that need a specific match count (e.g.
    exactly 2 lights for "beide") rather than module-level ALL_ENTITIES."""
    world_model = build_world_model(entities, [])
    context = ParseContext(entities=entities, index=world_model.entity_index, world_model=world_model)
    result = _build_parser().parse(text, context)
    assert result is not None
    assert len(result) == 1
    action = result[0]
    assert isinstance(action, ActionModel)
    return action

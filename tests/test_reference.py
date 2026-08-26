"""Phase 27 (v2 plan, "Pronomen und Referenzen"): pronoun and relative
references ("Mach es aus.", "Mach die auch an.", "Die Rollläden dort
runter.", "Die andere.") are resolved exclusively against the previous
turn's ``ConversationContext`` - never by guessing. Covers
``NluEngine.match_reference()`` directly, plus one end-to-end round-trip
(``match()`` -> build context -> ``match_reference()``) mirroring exactly
how ``conversation.py`` chains the two calls.
"""

from __future__ import annotations

from conftest import POLERAUM_COVERS
from ha_nlu.areas import AreaSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext

DIMMABLE_LIGHT = EntitySnapshot(
    "light.buerolicht", "Bürolicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)
OTHER_DIMMABLE_LIGHT = EntitySnapshot(
    "light.kuechenlicht", "Küchenlicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)
NON_DIMMABLE_LIGHT = EntitySnapshot(
    "light.altlicht", "Altlicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
SWITCH_A = EntitySnapshot(
    "switch.garagentor", "Garagentor", "switch", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
SWITCH_B = EntitySnapshot(
    "switch.sichtschutz", "Sichtschutz", "switch", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)

POLERAUM = AreaSnapshot(area_id="poleraum", name="Poleraum")

POLERAUM_LIGHT_1 = EntitySnapshot(
    "light.poleraum_decke", "Poleraum Decke", "light", "off",
    area_id="poleraum", area_name="Poleraum", capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
POLERAUM_LIGHT_2 = EntitySnapshot(
    "light.poleraum_wand", "Poleraum Wand", "light", "off",
    area_id="poleraum", area_name="Poleraum", capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
POLERAUM_LIGHT_3 = EntitySnapshot(
    "light.poleraum_stehlampe", "Poleraum Stehlampe", "light", "off",
    area_id="poleraum", area_name="Poleraum", capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)


def _context(
    last_entities: tuple[EntitySnapshot, ...] = (),
    last_area: AreaSnapshot | None = None,
) -> ConversationContext:
    return ConversationContext(
        last_command=None, last_entities=last_entities, last_area=last_area, pending_clarification=None,
    )


def test_match_reference_no_context(engine, entities):
    assert engine.match_reference("Mach es aus.", entities, None) is None


def test_match_reference_pronoun_turn_on(engine, entities):
    context = _context((SWITCH_A,))
    result = engine.match_reference("Mach es an.", entities, context)
    assert result is not None
    assert result.plan is not None
    assert result.plan.domain == "homeassistant"
    assert result.plan.service == "turn_on"
    assert result.plan.entity_id == "switch.garagentor"
    assert result.response_text == "Garagentor eingeschaltet."


def test_match_reference_accepts_discourse_connector(engine, entities):
    context = _context((SWITCH_A,))

    result = engine.match_reference("Dann mach es an.", entities, context)

    assert result is not None
    assert result.plan is not None
    assert result.plan.entity_id == "switch.garagentor"


def test_match_reference_pronoun_turn_off(engine, entities):
    context = _context((SWITCH_A,))
    result = engine.match_reference("Mach es aus.", entities, context)
    assert result is not None
    assert result.plan.service == "turn_off"
    assert result.plan.entity_id == "switch.garagentor"


def test_match_reference_pronoun_dreh_lass(engine, entities):
    # V4.1 "Advanced German Language": "dreh"/"lass" verbs on the pronoun form.
    context = _context((SWITCH_A,))
    result = engine.match_reference("Dreh es an.", entities, context)
    assert result is not None
    assert result.plan.service == "turn_on"
    result = engine.match_reference("Lass es aus.", entities, context)
    assert result is not None
    assert result.plan.service == "turn_off"


def test_match_reference_pronoun_turn_on_multiple(engine, entities):
    context = _context((SWITCH_A, SWITCH_B))
    result = engine.match_reference("Mach die auch an.", entities, context)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert sorted(result.plan.entity_id) == ["switch.garagentor", "switch.sichtschutz"]
    assert result.response_text == "2 Schalter eingeschaltet."


def test_match_reference_pronoun_returns_none_without_last_entities(engine, entities):
    context = _context(())
    assert engine.match_reference("Mach es an.", entities, context) is None


def test_match_reference_brighten(engine, entities):
    context = _context((DIMMABLE_LIGHT,))
    result = engine.match_reference("Mach es heller.", entities, context)
    assert result is not None
    assert result.plan.data == {"brightness_step_pct": 10}
    assert result.response_text == "Bürolicht um 10 Prozent heller gestellt."


def test_match_reference_dim(engine, entities):
    context = _context((DIMMABLE_LIGHT,))
    result = engine.match_reference("Mach es dunkler.", entities, context)
    assert result is not None
    assert result.plan.data == {"brightness_step_pct": -10}


def test_match_reference_brighten_returns_none_for_multiple_lights(engine, entities):
    context = _context((DIMMABLE_LIGHT, OTHER_DIMMABLE_LIGHT))
    assert engine.match_reference("Mach es heller.", entities, context) is None


def test_match_reference_brighten_returns_none_for_unsupported_capability(engine, entities):
    context = _context((NON_DIMMABLE_LIGHT,))
    assert engine.match_reference("Mach es heller.", entities, context) is None


def test_match_reference_area_anchored_close_single_cover(engine, quantifier_entities):
    single_area = AreaSnapshot(area_id="buero", name="Büro")
    entities_with_area = quantifier_entities + [
        EntitySnapshot("cover.rolllade_buero_2", "Rolllade Büro 2", "cover", "open", area_id="buero", area_name="Büro"),
    ]
    context = _context(last_area=single_area)
    result = engine.match_reference("Die Rollläden dort runter.", entities_with_area, context)
    assert result is not None
    assert result.plan.service == "close_cover"
    assert result.plan.entity_id == "cover.rolllade_buero_2"


def test_match_reference_area_anchored_open_multiple_covers(engine, quantifier_entities):
    context = _context(last_area=POLERAUM)
    result = engine.match_reference("Die Rollläden dort hoch.", quantifier_entities, context)
    assert result is not None
    assert result.plan.service == "open_cover"
    assert sorted(result.plan.entity_id) == ["cover.rolllade_poleraum_links", "cover.rolllade_poleraum_rechts"]
    assert result.response_text == "2 Rollläden geöffnet."


def test_match_reference_area_anchored_returns_none_without_last_area(engine, quantifier_entities):
    context = _context()
    assert engine.match_reference("Die Rollläden dort runter.", quantifier_entities, context) is None


def test_match_reference_area_anchored_returns_none_for_wrong_domain(engine, quantifier_entities):
    context = _context(last_area=POLERAUM)
    assert engine.match_reference("Der Ventilator dort runter.", quantifier_entities, context) is None


def test_match_reference_area_anchored_verb_first_dort_before_domain(engine, quantifier_entities):
    # HomeIntent plan V4.3 ("Implicit Targets"): the plan's own example is
    # verb-first with "dort" *before* the domain ("Mach dort die Rollläden
    # runter."), not just the pre-existing trailing "{domain} dort runter"
    # word order - same _resolve_area_anchored() resolution either way.
    single_area = AreaSnapshot(area_id="buero", name="Büro")
    entities_with_area = quantifier_entities + [
        EntitySnapshot("cover.rolllade_buero_2", "Rolllade Büro 2", "cover", "open", area_id="buero", area_name="Büro"),
    ]
    context = _context(last_area=single_area)
    result = engine.match_reference("Mach dort die Rollläden runter.", entities_with_area, context)
    assert result is not None
    assert result.plan.service == "close_cover"
    assert result.plan.entity_id == "cover.rolllade_buero_2"


def test_match_reference_area_anchored_verb_first_domain_before_dort(engine, quantifier_entities):
    context = _context(last_area=POLERAUM)
    result = engine.match_reference("Mach die Rollläden dort hoch.", quantifier_entities, context)
    assert result is not None
    assert result.plan.service == "open_cover"
    assert sorted(result.plan.entity_id) == ["cover.rolllade_poleraum_links", "cover.rolllade_poleraum_rechts"]


def test_match_reference_im_selben_raum_turn_on(engine):
    # HomeIntent plan V4.4 ("Relative Locations"): "im selben Raum" is the
    # same last-area-anchored concept "dort" already covers, just different
    # wording - same _resolve_area_anchored() resolution, now also reachable
    # for HassTurnOn/HassTurnOff (not just cover open/close).
    context = _context(last_area=POLERAUM)
    result = engine.match_reference("Mach die Lichter im selben Raum an.", [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2], context)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert sorted(result.plan.entity_id) == ["light.poleraum_decke", "light.poleraum_wand"]


def test_match_reference_im_selben_raum_turn_off(engine):
    context = _context(last_area=POLERAUM)
    result = engine.match_reference("Schalte die Lichter im selben Raum aus.", [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2], context)
    assert result is not None
    assert result.plan.service == "turn_off"
    assert sorted(result.plan.entity_id) == ["light.poleraum_decke", "light.poleraum_wand"]


def test_match_reference_im_selben_raum_returns_none_without_last_area(engine):
    context = _context()
    assert engine.match_reference("Mach die Lichter im selben Raum an.", [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2], context) is None


def test_match_reference_hier_turn_on(engine):
    # V6 architecture plan, V6.13 ("Relative Locations"): "hier" is the same
    # last-area-anchored concept "dort"/"im selben Raum" already cover, just
    # different wording - same _resolve_area_anchored() resolution.
    context = _context(last_area=POLERAUM)
    result = engine.match_reference("Mach die Lichter hier an.", [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2], context)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert sorted(result.plan.entity_id) == ["light.poleraum_decke", "light.poleraum_wand"]


def test_match_reference_hier_cover_hoch(engine, quantifier_entities):
    context = _context(last_area=POLERAUM)
    result = engine.match_reference("Die Rollläden hier hoch.", quantifier_entities, context)
    assert result is not None
    assert result.plan.service == "open_cover"
    assert sorted(result.plan.entity_id) == ["cover.rolllade_poleraum_links", "cover.rolllade_poleraum_rechts"]


def test_match_reference_hier_returns_none_without_last_area(engine):
    context = _context()
    assert engine.match_reference("Mach die Lichter hier an.", [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2], context) is None


def test_match_reference_ambiguous_reference_returns_none(engine, entities):
    context = _context((SWITCH_A,))
    assert engine.match_reference("Die andere.", entities, context) is None
    assert engine.match_reference("Die daneben.", entities, context) is None


def test_match_reference_returns_none_for_unrelated_sentence(engine, entities):
    context = _context((SWITCH_A,))
    assert engine.match_reference("Mach das Licht an.", entities, context) is None


def test_match_reference_others_turn_on_single_remaining(engine, entities):
    entities_with_lights = entities + [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2]
    context = _context((POLERAUM_LIGHT_1,), last_area=POLERAUM)
    result = engine.match_reference("Mach die anderen an.", entities_with_lights, context)
    assert result is not None
    assert result.plan.service == "turn_on"
    assert result.plan.entity_id == "light.poleraum_wand"
    assert result.response_text == "Poleraum Wand eingeschaltet."


def test_match_reference_others_turn_off_multiple_remaining(engine, entities):
    entities_with_lights = entities + [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2, POLERAUM_LIGHT_3]
    context = _context((POLERAUM_LIGHT_1,), last_area=POLERAUM)
    result = engine.match_reference("Mach die anderen auch aus.", entities_with_lights, context)
    assert result is not None
    assert result.plan.service == "turn_off"
    assert sorted(result.plan.entity_id) == ["light.poleraum_stehlampe", "light.poleraum_wand"]
    assert result.response_text == "2 Lichter ausgeschaltet."


def test_match_reference_others_returns_none_without_last_area(engine, entities):
    entities_with_lights = entities + [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2]
    context = _context((POLERAUM_LIGHT_1,))
    assert engine.match_reference("Mach die anderen an.", entities_with_lights, context) is None


def test_match_reference_others_returns_none_without_last_entities(engine, entities):
    context = _context((), last_area=POLERAUM)
    assert engine.match_reference("Mach die anderen an.", entities, context) is None


def test_match_reference_others_returns_none_when_none_remaining(engine, entities):
    entities_with_lights = entities + [POLERAUM_LIGHT_1, POLERAUM_LIGHT_2]
    context = _context((POLERAUM_LIGHT_1, POLERAUM_LIGHT_2), last_area=POLERAUM)
    assert engine.match_reference("Mach die anderen an.", entities_with_lights, context) is None


def test_match_reference_others_returns_none_for_mixed_domain_last_entities(engine, quantifier_entities):
    entities_with_lights = quantifier_entities + [POLERAUM_LIGHT_1]
    context = _context((POLERAUM_LIGHT_1, POLERAUM_COVERS[0]), last_area=POLERAUM)
    assert engine.match_reference("Mach die anderen an.", entities_with_lights, context) is None


def test_end_to_end_turn_on_then_pronoun_off(engine, entities):
    """Mirrors conversation.py's actual call chain: a successful match()
    builds a ``SemanticCommand``, whose resolved entities become the next
    turn's context - the plan's own literal "Mach es aus." example."""
    turn_on = engine.match("Mach das Garagentor an", entities)
    assert turn_on is not None
    assert turn_on.command is not None

    context = _context(tuple(turn_on.command.entities), turn_on.command.area)
    followup = engine.match_reference("Mach es aus.", entities, context)
    assert followup is not None
    assert followup.plan.entity_id == "switch.garagentor"
    assert followup.plan.service == "turn_off"

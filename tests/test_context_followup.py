"""Phase 26 (v2 plan, "Context"): elliptical follow-up commands that omit
their own target ("Etwas heller.") are resolved against the previous turn's
``ConversationContext`` instead of parsed as a fresh sentence. Covers
``NluEngine.match_followup()`` directly, plus one end-to-end round-trip
(``match()`` -> build context -> ``match_followup()``) mirroring exactly how
``conversation.py`` chains the two calls.

V6.23 ("Natural Context", HomeIntent plan V6 Teil 5/7) extended
``match_followup()`` beyond brightness-only: bare "wärmer"/"kälter" now
resolves against a single climate entity in context, reusing
``climate_extended/temperature.yaml``'s already-established
HassClimateIncreaseTemperature/HassClimateDecreaseTemperature vocabulary
(see engine.py's match_followup() docstring for why - "niemals raten").
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext

DIMMABLE_LIGHT = EntitySnapshot(
    "light.buerolicht", "Bürolicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
)
NON_DIMMABLE_LIGHT = EntitySnapshot(
    "light.altlicht", "Altlicht", "light", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
SWITCH = EntitySnapshot(
    "switch.garagentor", "Garagentor", "switch", "off",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
CLIMATE = EntitySnapshot(
    "climate.heizung_buero", "Heizung Büro", "climate", "heat",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}),
    attributes={"temperature": 20},
)


def _context(entities: tuple[EntitySnapshot, ...]) -> ConversationContext:
    return ConversationContext(
        last_command=None, last_entities=entities, last_area=None, pending_clarification=None,
    )


def test_match_followup_returns_none_without_context(engine):
    assert engine.match_followup("Etwas heller.", None) is None


def test_match_followup_returns_none_with_empty_context(engine):
    context = _context(())
    assert engine.match_followup("Etwas heller.", context) is None


def test_match_followup_returns_none_for_non_light_domain(engine):
    context = _context((SWITCH,))
    assert engine.match_followup("Etwas heller.", context) is None


def test_match_followup_returns_none_for_multiple_lights(engine):
    context = _context((DIMMABLE_LIGHT, NON_DIMMABLE_LIGHT))
    assert engine.match_followup("Etwas heller.", context) is None


def test_match_followup_brighten(engine):
    context = _context((DIMMABLE_LIGHT,))
    result = engine.match_followup("Etwas heller.", context)
    assert result is not None
    assert result.plan is not None
    assert result.plan.domain == "light"
    assert result.plan.service == "turn_on"
    assert result.plan.entity_id == "light.buerolicht"
    assert result.plan.data == {"brightness_step_pct": 10}
    assert result.response_text == "Bürolicht um 10 Prozent heller gestellt."


def test_match_followup_brighten_short_form(engine):
    context = _context((DIMMABLE_LIGHT,))
    result = engine.match_followup("Heller.", context)
    assert result is not None
    assert result.plan.data == {"brightness_step_pct": 10}


def test_match_followup_dim(engine):
    context = _context((DIMMABLE_LIGHT,))
    result = engine.match_followup("Etwas dunkler.", context)
    assert result is not None
    assert result.plan.data == {"brightness_step_pct": -10}
    assert result.response_text == "Bürolicht um 10 Prozent dunkler gestellt."


def test_match_followup_returns_none_for_unsupported_capability(engine):
    context = _context((NON_DIMMABLE_LIGHT,))
    assert engine.match_followup("Etwas heller.", context) is None


def test_match_followup_returns_none_for_unrelated_sentence(engine):
    context = _context((DIMMABLE_LIGHT,))
    assert engine.match_followup("Mach das Licht an.", context) is None


def test_match_followup_climate_warmer(engine):
    context = _context((CLIMATE,))
    result = engine.match_followup("Wärmer.", context)
    assert result is not None
    assert result.plan is not None
    assert result.plan.domain == "climate"
    assert result.plan.service == "set_temperature"
    assert result.plan.entity_id == "climate.heizung_buero"
    assert result.plan.data == {"temperature": 21}
    assert result.response_text == "Heizung Büro wärmer gestellt."


def test_match_followup_climate_kaelter(engine):
    context = _context((CLIMATE,))
    result = engine.match_followup("Kälter.", context)
    assert result is not None
    assert result.plan.data == {"temperature": 19}
    assert result.response_text == "Heizung Büro kälter gestellt."


def test_match_followup_warmer_returns_none_for_light_domain(engine):
    context = _context((DIMMABLE_LIGHT,))
    assert engine.match_followup("Wärmer.", context) is None


def test_match_followup_heller_returns_none_for_climate_domain(engine):
    context = _context((CLIMATE,))
    assert engine.match_followup("Etwas heller.", context) is None


def test_end_to_end_turn_on_then_brighten(engine):
    """Mirrors conversation.py's actual call chain: a successful match()
    builds a ``SemanticCommand``, whose resolved entities become the next
    turn's context - exactly the plan's own literal example."""
    turn_on = engine.match("Mach das Bürolicht an", [DIMMABLE_LIGHT])
    assert turn_on is not None
    assert turn_on.command is not None

    context = _context(tuple(turn_on.command.entities))
    followup = engine.match_followup("Etwas heller.", context)
    assert followup is not None
    assert followup.plan.entity_id == "light.buerolicht"
    assert followup.plan.data == {"brightness_step_pct": 10}

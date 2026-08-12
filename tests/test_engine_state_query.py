"""HomeIntent V4.2, "Semantic Query & State Resolution": HassStateQuery
(list/count), HassCheckState (singular boolean), HassExistsQuery (existence)
- the three intents StateQueryParser produces. Mirrors
tests/test_engine_comparisons.py's style: direct ``engine.match()`` calls
against synthetic ``EntitySnapshot`` fixtures.

Covers each operation x each result cardinality (0/1/N), area scoping, the
Milestone-1 ``allows_empty`` validator gating (0 matches for
list/count/exists is SUCCESS + EMPTY, never an error - Regel from the
spec), and the ``_STATE_QUERY_RE``/narrowed ``_COMPARISON_QUERY_RE`` routing
boundary that motivated this session's regex changes.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot

FENSTER_KELLER = EntitySnapshot(
    "binary_sensor.fenster_keller", "Fenster Keller", "binary_sensor", "on",
    area_id="keller", area_name="Keller", device_class="window",
)
FENSTER_BAD = EntitySnapshot(
    "binary_sensor.fenster_bad", "Fenster Bad", "binary_sensor", "off",
    area_id="bad", area_name="Bad", device_class="window",
)
TUER_EINGANG = EntitySnapshot(
    "binary_sensor.tuer_eingang", "Tür Eingang", "binary_sensor", "on",
    area_id="eingang", area_name="Eingang", device_class="door",
)
MOTION_FLUR = EntitySnapshot(
    "binary_sensor.bewegung_flur", "Bewegung Flur", "binary_sensor", "on",
    area_id="flur", area_name="Flur", device_class="motion",
)
LICHT_WOHNZIMMER = EntitySnapshot(
    "light.wohnzimmer", "Wohnzimmerlicht", "light", "on",
    area_id="wohnzimmer", area_name="Wohnzimmer",
)
LICHT_KUECHE = EntitySnapshot(
    "light.kueche", "Küchenlicht", "light", "off",
    area_id="kueche", area_name="Küche",
)

WINDOWS = [FENSTER_KELLER, FENSTER_BAD]
ALL_SENSORS = [FENSTER_KELLER, FENSTER_BAD, TUER_EINGANG, MOTION_FLUR]
LIGHTS = [LICHT_WOHNZIMMER, LICHT_KUECHE]


# --- HassStateQuery (list/count) ------------------------------------------


def test_state_query_list_single_match(engine):
    result = engine.match("welche Fenster sind offen", WINDOWS)
    assert result is not None
    assert result.plan is None  # query, never calls a service (Regel 3)
    assert result.command.entities == (FENSTER_KELLER,)
    assert result.response_text == "Fenster Keller ist offen."


def test_state_query_list_multiple_matches(engine):
    result = engine.match("welche Fenster sind geschlossen", [FENSTER_BAD, TUER_EINGANG])
    # Only FENSTER_BAD (window, off) is closed - TUER_EINGANG is a door, on.
    assert result is not None
    assert result.command.entities == (FENSTER_BAD,)


def test_state_query_list_empty_is_success_not_error(engine):
    # Regel: 0 matches for LIST_ENTITIES is SUCCESS + EMPTY, not an error.
    result = engine.match("welche Fenster sind geschlossen", [FENSTER_KELLER])
    assert result is not None
    assert result.command.entities == ()
    assert result.response_text == "Keine Fenster sind geschlossen."


def test_state_query_count_only_phrasing(engine):
    result = engine.match(
        "wie viele Fenster sind offen",
        [FENSTER_KELLER, EntitySnapshot(
            "binary_sensor.fenster_buero", "Fenster Büro", "binary_sensor", "on",
            area_id="buero", area_name="Büro", device_class="window",
        )],
    )
    assert result is not None
    assert len(result.command.entities) == 2
    assert result.response_text == "2 Fenster sind offen."


def test_state_query_area_scoped(engine):
    # HassStateQuery's grammar puts the area before the state word
    # ("welche {device_class} sind [area] {state}"), matching how this
    # phrasing reads most naturally in German.
    result = engine.match("welche Fenster sind im Keller offen", WINDOWS)
    assert result is not None
    assert result.command.entities == (FENSTER_KELLER,)


def test_state_query_area_scoped_no_matches_still_empty_success(engine):
    result = engine.match("welche Fenster sind im Bad offen", WINDOWS)
    assert result is not None
    assert result.command.entities == ()


def test_state_query_unknown_area_returns_none(engine):
    assert engine.match("welche Fenster sind im Bunker offen", WINDOWS) is None


def test_state_query_noch_filler_word(engine):
    # Live incident (v4.2 Milestone 7): "noch" (still/yet) is idiomatic
    # German and was one of the two originally-reported failing sentences
    # ("Welche Fenster sind noch geöffnet?") - the grammar had no optional
    # filler for it and returned NOT_UNDERSTOOD. Carries no semantic weight
    # (SemanticState unchanged), so this must resolve identically to the
    # "noch"-less phrasing.
    result = engine.match("welche Fenster sind noch offen", WINDOWS)
    assert result is not None
    assert result.command.entities == (FENSTER_KELLER,)


def test_state_query_area_scoped_noch_filler_word(engine):
    result = engine.match("welche Fenster sind im Keller noch offen", WINDOWS)
    assert result is not None
    assert result.command.entities == (FENSTER_KELLER,)


def test_state_query_denn_filler_word(engine):
    # Spec gap #2: "denn" (rhetorical-question filler, "Sind denn Fenster
    # offen?") carries no semantic weight, same as "noch" above.
    result = engine.match("welche Fenster sind denn offen", WINDOWS)
    assert result is not None
    assert result.command.entities == (FENSTER_KELLER,)


def test_state_query_bare_sentence_no_welche_or_wie_viele(engine):
    # Spec gap #3: "Sind Fenster noch offen?" has neither "welche" nor "wie
    # viele" - a third, equally natural German phrasing. Routing already
    # worked ("sind" is an existing _STATE_QUERY_RE trigger word); only the
    # grammar template itself was missing.
    result = engine.match("sind Fenster noch offen", WINDOWS)
    assert result is not None
    assert result.command.entities == (FENSTER_KELLER,)


def test_state_query_bare_sentence_area_scoped(engine):
    result = engine.match("sind im Keller Fenster offen", WINDOWS)
    assert result is not None
    assert result.command.entities == (FENSTER_KELLER,)


def test_state_query_motion_binary_sensor_uses_on_off_not_open_closed(engine):
    # SemanticState branching: a motion binary_sensor's "an"/"aus" maps to
    # ON/OFF, not OPEN/CLOSED - a "welche ... sind offen" query must not
    # match it even though its raw HA state is "on".
    result = engine.match("welche Bewegungsmelder sind eingeschaltet", ALL_SENSORS)
    assert result is not None
    assert result.command.entities == (MOTION_FLUR,)


# --- HassCheckState (singular boolean) -------------------------------------


def test_check_state_positive(engine):
    result = engine.match("ist das Fenster Keller offen", WINDOWS)
    assert result is not None
    assert result.plan is None
    assert result.response_text == "Ja, Fenster Keller ist offen."


def test_check_state_negative(engine):
    result = engine.match("ist das Fenster Bad offen", WINDOWS)
    assert result is not None
    assert result.response_text == "Nein, Fenster Bad ist nicht offen."


def test_check_state_area_scoped(engine):
    result = engine.match("ist die Tür Eingang im Eingang offen", ALL_SENSORS)
    assert result is not None
    assert result.response_text == "Ja, Tür Eingang ist offen."


def test_check_state_noch_filler_word(engine):
    # Same "noch" gap as HassStateQuery (see test_state_query_noch_filler_word)
    # - "Ist das Fenster Keller noch offen?" is equally idiomatic German.
    result = engine.match("ist das Fenster Keller noch offen", WINDOWS)
    assert result is not None
    assert result.response_text == "Ja, Fenster Keller ist offen."


def test_check_state_area_scoped_noch_filler_word(engine):
    result = engine.match("ist die Tür Eingang im Eingang noch offen", ALL_SENSORS)
    assert result is not None
    assert result.response_text == "Ja, Tür Eingang ist offen."


def test_check_state_area_scoped_word_order_does_not_pick_decoy_entity(engine):
    # Live incident (v4.2 Milestone 7): the area-scoped HassCheckState
    # sentence must be tried before the bare one in state_query.yaml, or
    # {name} (an open wildcard) swallows "{name} im {area}" whole and never
    # resolves {area} at all. That alone is silent - the real danger is a
    # second entity whose friendly_name equals just the area word ("Fenster
    # im Schlafzimmer" spoken text still fuzzy-matches an entity literally
    # named "Schlafzimmer" via the resolver's substring scoring), which then
    # gets answered instead of the actually-asked-about entity - a Regel 4
    # violation (never guess) that a "does this return a result at all"
    # check wouldn't catch. Names are in "item area" spoken order but
    # "area item" friendly_name order specifically because that mismatch is
    # what made the decoy win before the grammar fix.
    schlafzimmer_fenster = EntitySnapshot(
        "binary_sensor.schlafzimmer_fenster", "Schlafzimmer Fenster", "binary_sensor", "off",
        area_id="schlafzimmer", area_name="Schlafzimmer", device_class="window",
    )
    schlafzimmer_rollladen_decoy = EntitySnapshot(
        "cover.schlafzimmer_decoy", "Schlafzimmer", "cover", "open",
        area_id="schlafzimmer", area_name="Schlafzimmer",
    )
    result = engine.match(
        "ist das Fenster im Schlafzimmer geöffnet",
        [schlafzimmer_fenster, schlafzimmer_rollladen_decoy],
    )
    assert result is not None
    assert result.command.entities == (schlafzimmer_fenster,)
    assert result.response_text == "Nein, Schlafzimmer Fenster ist nicht offen."


def test_check_state_unresolved_name_returns_none(engine):
    # Never guess (Regel 4): an unknown/ambiguous singular name never falls
    # back to a clarification round-trip here, unlike SingleTargetParser.
    assert engine.match("ist das Fenster Garage offen", WINDOWS) is None


def test_check_state_ambiguous_name_returns_none(engine):
    duplicate_named = [
        EntitySnapshot("binary_sensor.f1", "Fenster", "binary_sensor", "on", device_class="window"),
        EntitySnapshot("binary_sensor.f2", "Fenster", "binary_sensor", "off", device_class="window"),
    ]
    assert engine.match("ist das Fenster offen", duplicate_named) is None


# --- HassExistsQuery (existence) --------------------------------------------


def test_exists_query_true_with_state_filter(engine):
    result = engine.match("gibt es offene Fenster", WINDOWS)
    assert result is not None
    assert result.response_text == "Ja, es gibt 1 Fenster."


def test_exists_query_false_with_state_filter(engine):
    result = engine.match("gibt es offene Fenster", [FENSTER_BAD])
    assert result is not None
    assert result.response_text == "Nein, es gibt keine Fenster."


def test_exists_query_bare_no_state_word(engine):
    # HassExistsQuery's bare "gibt es {device_class}" sentence carries no
    # state word at all - must still route to StateQueryParser, not fall
    # through to "not understood" (the second of the two live routing bugs
    # fixed this session).
    result = engine.match("gibt es Fenster im Keller", WINDOWS)
    assert result is not None
    assert result.response_text == "Ja, es gibt 1 Fenster."


def test_exists_query_device_class_before_area_word_order(engine):
    # Both German word orders are natural for HassExistsQuery - "gibt es
    # Fenster im Keller" (device_class before area) must work, not just
    # "gibt es im Keller Fenster" (area before device_class).
    result = engine.match("gibt es geschlossene Fenster im Bad", WINDOWS)
    assert result is not None
    assert result.response_text == "Ja, es gibt 1 Fenster."


def test_exists_query_area_scoped_false(engine):
    result = engine.match("gibt es offene Fenster im Bad", WINDOWS)
    assert result is not None
    assert result.response_text == "Nein, es gibt keine Fenster."


def test_exists_query_noch_filler_word(engine):
    # Spec gap #1: "gibt es noch offene Fenster?" (still/yet) - HassExistsQuery
    # had no "[noch]" while HassStateQuery/HassCheckState already did.
    result = engine.match("gibt es noch offene Fenster", WINDOWS)
    assert result is not None
    assert result.response_text == "Ja, es gibt 1 Fenster."


def test_exists_query_denn_filler_word(engine):
    result = engine.match("gibt es denn offene Fenster", WINDOWS)
    assert result is not None
    assert result.response_text == "Ja, es gibt 1 Fenster."


def test_exists_query_ist_ein_word_order(engine):
    # Spec gap #4: "Ist ein Fenster offen?" - existence phrased with "ist"/
    # indefinite article instead of "gibt es". Still EXISTS semantics (no
    # specific named entity requested), not HassCheckState.
    result = engine.match("ist ein Fenster offen", WINDOWS)
    assert result is not None
    assert result.frame.intent == "HassExistsQuery"
    assert result.response_text == "Ja, es gibt 1 Fenster."


def test_exists_query_ist_ein_area_scoped_word_order(engine):
    result = engine.match("ist im Bad ein Fenster offen", WINDOWS)
    assert result is not None
    assert result.frame.intent == "HassExistsQuery"
    assert result.response_text == "Nein, es gibt keine Fenster."


def test_exists_query_ist_ein_does_not_shadow_check_state(engine):
    # The "ist ein {device_class} ... {state}" grammar (added for gap #4)
    # must not swallow a real named-entity HassCheckState question just
    # because HassExistsQuery is now declared first in the YAML file for
    # ordering reasons (see state_query.yaml's comment) - a real "die/der/das"
    # article must still resolve to the named entity.
    result = engine.match("ist das Fenster Keller offen", WINDOWS)
    assert result is not None
    assert result.frame.intent == "HassCheckState"
    assert result.response_text == "Ja, Fenster Keller ist offen."


# --- Routing boundary -------------------------------------------------------


def test_plain_on_off_command_not_misrouted_to_state_query(engine):
    # "Schalte das Licht aus" contains "aus" but none of _STATE_QUERY_RE's
    # trigger words - must still reach the plain on/off command pipeline.
    result = engine.match("schalte das Küchenlicht aus", LIGHTS)
    assert result is not None
    assert result.plan is not None
    assert result.plan.service == "turn_off"


def test_welche_without_comparator_or_state_word_not_misrouted(engine):
    # A bare "welche" sentence with neither a comparator word (narrowed
    # _COMPARISON_QUERY_RE) nor a state word (_STATE_QUERY_RE) falls through
    # to "not understood" rather than being swallowed by either grammar.
    assert engine.match("welche Lichter gibt es normalerweise", LIGHTS) is None


def test_comparison_query_still_routes_to_comparison_parser_not_state_query(engine):
    # "welche Lichter sind mindestens 50 Prozent" has no state word at all,
    # so it must stay on ComparisonQueryParser's grammar, not get swallowed
    # by _STATE_QUERY_RE.
    bright_light = EntitySnapshot(
        "light.hell", "Helles Licht", "light", "on", attributes={"brightness": 255},
    )
    result = engine.match("welche Lichter sind mindestens 50 Prozent", [bright_light])
    assert result is not None
    assert result.frame.intent == "HassQueryComparison"

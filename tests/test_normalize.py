"""Phase 3 (v2 plan): normalize() runs before any parser. Kept small on
purpose - hassil already tolerates case, extra whitespace and trailing
punctuation natively (verified against the real engine below); this module
only covers what hassil does not: the "%" symbol and (HomeIntent plan
V4.1) a fixed set of German filler particles."""

from __future__ import annotations

from ha_nlu.nlu.normalize import normalize


def test_collapses_repeated_whitespace_and_strips():
    assert normalize("  Mach   das Licht   an ") == "Mach das Licht an"


def test_percent_symbol_with_space_becomes_word():
    assert normalize("mach das Licht auf 50 %") == "mach das Licht auf 50 Prozent"


def test_percent_symbol_without_space_becomes_word():
    assert normalize("mach das Licht auf 50%") == "mach das Licht auf 50 Prozent"


def test_leaves_already_normalized_text_unchanged():
    assert normalize("mach das Licht auf 50 Prozent") == "mach das Licht auf 50 Prozent"


def test_degree_symbol_with_space_becomes_word():
    assert normalize("stelle die Heizung auf 21 °") == "stelle die Heizung auf 21 Grad"


def test_degree_symbol_without_space_becomes_word():
    assert normalize("stelle die Heizung auf 21°") == "stelle die Heizung auf 21 Grad"


def test_does_not_touch_entity_names_semantically():
    # normalize() must not make resolution decisions - casing/spelling of a
    # spoken device name is passed through untouched (see module docstring).
    assert normalize("Mach die Wohnzimmerlampe an") == "Mach die Wohnzimmerlampe an"


def test_engine_still_matches_percent_symbol_end_to_end(engine, entities):
    # Regression: normalize() replaces the ad-hoc _normalize_percent_symbol
    # that used to live in engine.py directly (see architecture-v2-phase3.md).
    result = engine.match("Stelle den Rollladen Wohnzimmer auf 30%", entities)
    assert result is not None
    assert result.plan.data == {"position": 30}


def test_strips_mal_doch_kurz_etwas_ein_bisschen():
    assert normalize("mach mal das Licht an") == "mach das Licht an"
    assert normalize("mach doch das Licht an") == "mach das Licht an"
    assert normalize("mach kurz das Licht an") == "mach das Licht an"
    assert normalize("mach etwas das Licht an") == "mach das Licht an"
    assert normalize("mach ein bisschen das Licht an") == "mach das Licht an"


def test_preserves_degree_words_before_relative_adjustments():
    assert normalize("mach das Licht etwas heller") == "mach das Licht etwas heller"
    assert normalize("mach es ein bisschen wärmer") == "mach es ein bisschen wärmer"


def test_filler_stripping_is_case_insensitive():
    assert normalize("Mach Mal das Licht an") == "Mach das Licht an"


def test_does_not_strip_filler_words_as_substrings():
    # "mal" only strips as its own token - "einmal"/"Dochlicht" would be a
    # different (unrelated) word, never split mid-token.
    assert normalize("mach das Licht einmal an") == "mach das Licht einmal an"


def test_does_not_strip_bitte():
    # "bitte" is deliberately excluded - see module docstring: some
    # sentences (e.g. "bitte {name} an") use it as their only imperative
    # marker with no separate verb.
    assert normalize("bitte das Licht an") == "bitte das Licht an"


def test_short_cover_imperative_is_normalized_without_touching_names():
    assert normalize("Fahr die Rollläden hoch") == "fahre die Rollläden hoch"
    assert normalize("Bitte fahr die Rollläden runter") == (
        "Bitte fahre die Rollläden runter"
    )
    assert normalize("Mach das Fahr Licht an") == "Mach das Fahr Licht an"


def test_engine_matches_filler_words_end_to_end(engine, entities):
    # V4.1 "Advanced German Language": filler particles must not block a
    # match that would otherwise succeed.
    result = engine.match("mach doch das Treppenlicht an", entities)
    assert result is not None
    assert result.plan.entity_id == "light.treppen_licht_gruppe"

    result = engine.match("schalte kurz das Treppenlicht aus", entities)
    assert result is not None
    assert result.plan.service == "turn_off"

    result = engine.match("mach ein bisschen das Flurlicht an", entities)
    assert result is not None
    assert result.plan.entity_id == "light.flur_licht"


def test_normalizes_natural_request_shells_without_resolving_entities():
    assert normalize("Wäre es möglich, das Küchenlicht einzuschalten?") == (
        "bitte das Küchenlicht einschalten?"
    )
    assert normalize("Ich hätte gerne das Küchenlicht an") == "bitte das Küchenlicht an"
    assert normalize("Sorge bitte dafür, dass das Küchenlicht an ist") == (
        "bitte das Küchenlicht an ist"
    )


def test_normalizes_query_shells_and_separable_infinitives():
    assert normalize("Sag mir bitte, wie warm es im Wohnzimmer ist") == (
        "wie warm es im Wohnzimmer ist"
    )
    assert normalize("Wie steht es um die Luftfeuchtigkeit im Wohnzimmer?") == (
        "wie ist Luftfeuchtigkeit im Wohnzimmer?"
    )
    assert normalize("das Licht ein zu schalten") == "das Licht einschalten"
    assert normalize("Was zeigt der Temperatursensor im Wohnzimmer an?") == (
        "Temperatur im Wohnzimmer"
    )


def test_normalizes_fractions_and_german_number_compounds():
    assert normalize("Rollladen auf drei Viertel") == "Rollladen auf 75 Prozent"
    assert normalize("Rollladen zur Hälfte") == "Rollladen auf 50 Prozent"
    assert normalize("auf zweiundzwanzig Grad") == "auf 22 Grad"
    assert normalize("auf siebzehn Grad") == "auf 17 Grad"

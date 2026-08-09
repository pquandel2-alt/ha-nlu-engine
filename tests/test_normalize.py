"""Phase 3 (v2 plan): normalize() runs before any parser. Kept small on
purpose - hassil already tolerates case, extra whitespace and trailing
punctuation natively (verified against the real engine below); this module
only covers what hassil does not: the "%" symbol."""

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

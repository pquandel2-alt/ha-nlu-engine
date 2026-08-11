"""HassSetPercentage: percent-target control for cover position / light
brightness. One grammar for both - which service call applies is decided
by the *resolved entity's domain*, not by the verb (see PERCENT_INTENTS in
service_call.py). This was a deliberate redesign after the original
verb-split grammar (HassSetPosition vs. HassLightSet) turned out to reject
valid generic-verb phrasings ("Stelle die Rollade auf 30 Prozent") for
covers, since only the light grammar accepted "stelle"."""

from __future__ import annotations

import pytest


def test_fahre_rolllade_buro_auf_30_prozent_runter(engine, entities):
    # Regression case from the real-world requirement ("Fahre die Rolllade
    # im Büro auf 30 Prozent runter/hoch"), spelled here to match this
    # fixture's actual friendly name "Rollladen Büro" - the colloquial
    # "Rolllade" (missing the final n) not matching it is a pre-existing,
    # correct resolve_entity behaviour (no letter may go missing in a
    # contains-match), unrelated to percent support itself.
    result = engine.match("Fahre den Rollladen im Büro auf 30 Prozent runter", entities)
    assert result is not None
    assert result.plan.domain == "cover"
    assert result.plan.service == "set_cover_position"
    assert result.plan.entity_id == "cover.rolllade_buro"
    assert result.plan.data == {"position": 30}


def test_mach_licht_auf_50_prozent(engine, entities):
    result = engine.match("mach das Treppenlicht auf 50 Prozent", entities)
    assert result is not None
    assert result.plan.domain == "light"
    assert result.plan.service == "turn_on"
    assert result.plan.entity_id == "light.treppen_licht_gruppe"
    assert result.plan.data == {"brightness_pct": 50}


def test_setze_rollladen_auf_100_prozent(engine, entities):
    result = engine.match("setze den Rollladen Wohnzimmer auf 100 Prozent", entities)
    assert result is not None
    assert result.plan.entity_id == "cover.rolllade_wohnzimmer"
    assert result.plan.data == {"position": 100}


def test_stelle_rollladen_auf_prozent_generic_verb_works_for_cover(engine, entities):
    # Real-world regression: "stelle"/"mach" are generic German verbs used
    # for both covers and lights - a cover-position sentence using the
    # "light-flavoured" verb must still resolve correctly by domain.
    result = engine.match("Stelle den Rollladen Wohnzimmer auf 40 Prozent", entities)
    assert result is not None
    assert result.plan.domain == "cover"
    assert result.plan.service == "set_cover_position"
    assert result.plan.data == {"position": 40}


def test_percent_symbol_instead_of_word(engine, entities):
    # Real-world regression: users type "30%" in the Assist chat UI, not
    # the word "Prozent".
    result = engine.match("Stelle den Rollladen Wohnzimmer auf 30%", entities)
    assert result is not None
    assert result.plan.data == {"position": 30}


def test_percent_symbol_no_space(engine, entities):
    result = engine.match("mach das Treppenlicht auf 50%", entities)
    assert result is not None
    assert result.plan.data == {"brightness_pct": 50}


def test_trailing_verb_phrasing(engine, entities):
    # "kannst du <name> auf <percent> Prozent fahren/dimmen/einstellen/stellen"
    result = engine.match("kannst du den Rollladen Wohnzimmer auf 60 Prozent fahren", entities)
    assert result is not None
    assert result.plan.data == {"position": 60}


def test_bare_number_no_unit_word_means_percent(engine, entities):
    # HomeIntent plan V4.2 ("Number Normalization"): "50" alone must
    # normalize to the same semantic value as "50 Prozent"/"50%" - safe to
    # infer here since the resolved entity's domain (cover/light) has no
    # other numeric parameter this grammar could mean.
    result = engine.match("Stelle den Rollladen Wohnzimmer auf 50", entities)
    assert result is not None
    assert result.plan.data == {"position": 50}


def test_bare_number_trailing_verb_phrasing(engine, entities):
    result = engine.match("kannst du das Treppenlicht auf 30 dimmen", entities)
    assert result is not None
    assert result.plan.data == {"brightness_pct": 30}


def test_bare_number_on_switch_domain_still_returns_none(engine, entities):
    # A bare number is only unambiguous for the two percent-capable domains
    # (cover/light) - switch has no percent semantics at all, same as the
    # "mach den Garagentor auf 50 Prozent" case below.
    assert engine.match("mach den Garagentor auf 50", entities) is None


@pytest.mark.parametrize(
    "text",
    [
        "mach das Unbekanntgerät auf 50 Prozent",  # unknown name
        "mach den Garagentor auf 50 Prozent",  # switch domain has no percent semantics
        "Rollladen Wohnzimmer auf 50 Prozent",  # missing verb - must not guess
    ],
)
def test_unmatched_percentage_returns_none(engine, entities, text):
    assert engine.match(text, entities) is None

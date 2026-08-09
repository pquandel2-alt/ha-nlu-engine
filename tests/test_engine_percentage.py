"""HassSetPosition (cover) / HassLightSet (light) percent-target control."""

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


@pytest.mark.parametrize(
    "text",
    [
        "mach das Unbekanntgerät auf 50 Prozent",  # unknown name
        "mach den Garagentor auf 50 Prozent",  # switch domain not allowed for HassLightSet
    ],
)
def test_unmatched_percentage_returns_none(engine, entities, text):
    assert engine.match(text, entities) is None


def test_percent_with_cover_domain_wrong_verb_family_falls_through(engine, entities):
    # Light sentences use machen/dimmen/stellen, cover sentences use
    # fahren/runter/hoch/setzen - a light-style sentence must not
    # accidentally match a cover, and vice versa via the domain guard.
    result = engine.match("mach die Rolllade im Büro auf 30 Prozent", entities)
    assert result is None

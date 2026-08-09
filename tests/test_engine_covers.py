"""HassOpenCover/HassCloseCover over cover entities."""

from __future__ import annotations

import pytest

from conftest import COVER_CLOSE_PHRASES, COVER_OPEN_PHRASES, COVERS


def _cases(phrases: list[str], names: dict[str, str]):
    for name, eid in names.items():
        for tpl in phrases:
            yield pytest.param(tpl.format(name=name), eid, id=f"{eid}:{tpl}")


OPEN_CASES = list(_cases(COVER_OPEN_PHRASES, COVERS))
CLOSE_CASES = list(_cases(COVER_CLOSE_PHRASES, COVERS))


@pytest.mark.parametrize("text,entity_id", OPEN_CASES)
def test_open_cover(engine, entities, text, entity_id):
    result = engine.match(text, entities)
    assert result is not None, f"no match for {text!r}"
    assert result.plan.domain == "cover"
    assert result.plan.service == "open_cover"
    assert result.plan.entity_id == entity_id


@pytest.mark.parametrize("text,entity_id", CLOSE_CASES)
def test_close_cover(engine, entities, text, entity_id):
    result = engine.match(text, entities)
    assert result is not None, f"no match for {text!r}"
    assert result.plan.domain == "cover"
    assert result.plan.service == "close_cover"
    assert result.plan.entity_id == entity_id


def test_domain_guard_light_intent_rejects_cover(engine, entities):
    # HassTurnOn/Off only allow light/switch/fan - a cover must not match.
    assert engine.match("Mach den Rollladen Büro an", entities) is None


@pytest.mark.parametrize(
    "text,entity_id",
    [
        ("fahre den Rollladen im Büro hoch", "cover.rolllade_buro"),
        ("öffne den Rollladen im Büro", "cover.rolllade_buro"),
        ("öffne den Rollladen in der Küche", "cover.rolllade_3"),
        ("fahre den Rollladen in dem Wohnzimmer hoch", "cover.rolllade_wohnzimmer"),
        ("kannst du den Rollladen Büro hochfahren", "cover.rolllade_buro"),
        ("bitte den Rollladen Büro hoch", "cover.rolllade_buro"),
        ("den Rollladen Büro öffnen", "cover.rolllade_buro"),
    ],
)
def test_open_cover_natural_prepositional_phrasing(engine, entities, text, entity_id):
    # Real speech puts the room in a prepositional phrase ("im Büro") rather
    # than HA's terse friendly-name style - the wildcard {name} slot swallows
    # the preposition verbatim, so it must be stripped before entity lookup.
    result = engine.match(text, entities)
    assert result is not None, f"no match for {text!r}"
    assert result.plan.domain == "cover"
    assert result.plan.service == "open_cover"
    assert result.plan.entity_id == entity_id


def test_close_cover_infinitive_and_politeness_forms(engine, entities):
    for text in ["den Rollladen Büro schließen", "kannst du den Rollladen Büro runterfahren", "bitte den Rollladen Büro runter"]:
        result = engine.match(text, entities)
        assert result is not None, f"no match for {text!r}"
        assert result.plan.service == "close_cover"
        assert result.plan.entity_id == "cover.rolllade_buro"

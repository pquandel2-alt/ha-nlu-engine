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

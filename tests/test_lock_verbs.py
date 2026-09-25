"""Everyday German lock verbs reach the lock domain; safety forms still refuse."""

from __future__ import annotations

import pytest

from homeintent.engine import NluEngine
from homeintent.entities import EntitySnapshot

SCHLOSS = EntitySnapshot(
    "lock.schatzkammer_schloss", "Schatzkammer Schloss", "lock", "locked",
    area_id="schatz", area_name="Schatzkammer", aliases=("Schatztür",),
)


@pytest.fixture(scope="module")
def engine() -> NluEngine:
    return NluEngine()


@pytest.mark.parametrize(
    ("sentence", "service"),
    (
        ("Entriegle die Schatztür.", "unlock"),
        ("Verriegle die Schatztür.", "lock"),
        ("Entriegle das Schloss in der Schatzkammer.", "unlock"),
        ("Verriegle das Schatzkammer Schloss.", "lock"),
        ("Sperre die Schatztür ab.", "lock"),
        ("Sperr die Schatztür auf.", "unlock"),
        ("Schließe die Schatztür ab.", "lock"),
    ),
)
def test_lock_verbs_build_a_lock_plan(engine, sentence, service):
    result = engine.match(sentence, [SCHLOSS])

    assert result is not None and result.plan is not None, sentence
    assert (result.plan.domain, result.plan.service) == ("lock", service)
    assert result.plan.entity_id == "lock.schatzkammer_schloss"


@pytest.mark.parametrize(
    "sentence",
    (
        "Entriegle nicht die Schatztür.",
        "Soll ich die Schatztür entriegeln?",
        "Entriegle die Schatztür vielleicht.",
    ),
)
def test_lock_safety_forms_never_build_a_plan(engine, sentence):
    result = engine.match(sentence, [SCHLOSS])

    assert result is None or result.plan is None, sentence


def test_room_with_a_single_lock_resolves_but_always_needs_confirmation(engine):
    from homeintent.risk import RiskLevel, classify_service_plan, requires_confirmation

    result = engine.match("Entriegle die Schatzkammer.", [SCHLOSS])

    assert result is not None and result.plan is not None
    assert result.plan.service == "unlock"
    assert classify_service_plan(result.plan, [SCHLOSS]) is RiskLevel.CRITICAL
    assert requires_confirmation(result.plan, [SCHLOSS])

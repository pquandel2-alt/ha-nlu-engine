"""Diagnostic matrix for exclusions before and after separable particles.

The same exclusion must select the same entities independently of German word
order, spelling variant, or an optional article.  This file deliberately pins
the v4.49.0 defect before production code is changed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ha_nlu.engine import MatchResult, NluEngine
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.capabilities import derive_capabilities


@dataclass(frozen=True)
class ExclusionCase:
    text: str
    expected_entity_ids: frozenset[str]


def _entity(entity_id: str, friendly_name: str, domain: str) -> EntitySnapshot:
    capabilities = frozenset(
        capability.name for capability in derive_capabilities(domain, None, {})
    )
    return EntitySnapshot(
        entity_id=entity_id,
        friendly_name=friendly_name,
        domain=domain,
        state="on",
        capabilities=capabilities,
    )


_ENTITIES = [
    _entity("light.kueche", "Küchenlicht", "light"),
    _entity("light.flur", "Flurlicht", "light"),
    _entity("light.bad", "Badlicht", "light"),
    _entity("switch.kueche", "Küchenschalter", "switch"),
    _entity("switch.flur", "Flurschalter", "switch"),
    _entity("switch.bad", "Badschalter", "switch"),
]

_LIGHT_TARGETS = frozenset({"light.flur", "light.bad"})
_SWITCH_TARGETS = frozenset({"switch.flur", "switch.bad"})

_CASES = (
    ExclusionCase(
        "Schalte alle Lichter aus außer dem Küchenlicht", _LIGHT_TARGETS
    ),
    ExclusionCase(
        "Schalte alle Lichter außer dem Küchenlicht aus", _LIGHT_TARGETS
    ),
    ExclusionCase("Schalte alle Lichter aus außer Küchenlicht", _LIGHT_TARGETS),
    ExclusionCase("Schalte alle Lichter außer Küchenlicht aus", _LIGHT_TARGETS),
    ExclusionCase(
        "Schalte alle Lichter aus ausser dem Küchenlicht", _LIGHT_TARGETS
    ),
    ExclusionCase(
        "Schalte alle Lichter ausser dem Küchenlicht aus", _LIGHT_TARGETS
    ),
    ExclusionCase("Schalte alle Lichter aus ausser Küchenlicht", _LIGHT_TARGETS),
    ExclusionCase("Schalte alle Lichter ausser Küchenlicht aus", _LIGHT_TARGETS),
    ExclusionCase(
        "Schalte alle Lichter aus mit Ausnahme von dem Küchenlicht",
        _LIGHT_TARGETS,
    ),
    ExclusionCase(
        "Schalte alle Lichter mit Ausnahme von dem Küchenlicht aus",
        _LIGHT_TARGETS,
    ),
    ExclusionCase(
        "Schalte alle Lichter aus mit Ausnahme von Küchenlicht", _LIGHT_TARGETS
    ),
    ExclusionCase(
        "Schalte alle Lichter mit Ausnahme von Küchenlicht aus", _LIGHT_TARGETS
    ),
    ExclusionCase(
        "Schalte alle Schalter aus außer dem Küchenschalter", _SWITCH_TARGETS
    ),
    ExclusionCase(
        "Schalte alle Schalter außer dem Küchenschalter aus", _SWITCH_TARGETS
    ),
)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.text)
def test_exclusion_never_targets_the_excepted_entity(case: ExclusionCase) -> None:
    result = NluEngine().match(case.text, _ENTITIES)

    assert isinstance(result, MatchResult), f"actual result: {result!r}"
    assert result.plan is not None, f"actual result: {result!r}"
    assert result.plan.service == "turn_off"
    actual = result.plan.entity_id
    actual_entity_ids = frozenset({actual} if isinstance(actual, str) else actual)
    assert actual_entity_ids == case.expected_entity_ids

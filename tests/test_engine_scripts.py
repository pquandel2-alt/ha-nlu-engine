"""Skript-Aktivierung (2026-08-20): HassRunScript over script entities -
"script.turn_on" is HA's documented way to run a script, mirrored from
xiaozhi_entity_mcp's own dedicated ``run_script`` tool (see service_call.py's
module docstring and its ``HassRunScript`` entry). Structurally the same
single-domain {name}-wildcard pattern as test_engine_covers.py."""

from __future__ import annotations

import pytest

from conftest import RUN_SCRIPT_PHRASES, SCRIPTS


def _cases(phrases: list[str], names: dict[str, str]):
    for name, eid in names.items():
        for tpl in phrases:
            yield pytest.param(tpl.format(name=name), eid, id=f"{eid}:{tpl}")


RUN_CASES = list(_cases(RUN_SCRIPT_PHRASES, SCRIPTS))


@pytest.mark.parametrize("text,entity_id", RUN_CASES)
def test_run_script(engine, script_entities, text, entity_id):
    result = engine.match(text, script_entities)
    assert result is not None, f"no match for {text!r}"
    assert result.plan.domain == "script"
    assert result.plan.service == "turn_on"
    assert result.plan.entity_id == entity_id


def test_domain_guard_run_script_rejects_light(engine, entities):
    # HassRunScript only allows "script" - a light must not match, same
    # domain-guard contract test_engine_covers.py's own guard test pins.
    assert engine.match("Starte Treppenlicht", entities) is None


def test_turn_on_intent_does_not_accept_a_script(engine, script_entities):
    # HassTurnOn stays scoped to light/switch/fan/climate - scripts get
    # their own dedicated HassRunScript instead (see service_call.py).
    assert engine.match("Schalte Gute Nacht ein", script_entities) is None


def test_aktiviere_reaches_run_script_despite_the_automation_enable_precheck(
    engine, script_entities,
):
    # conversation.py's cascade tries match_automation_enable() first for
    # any sentence containing "aktivier..." (Wave 11's _AUTOMATION_ENABLE_RE)
    # - here pinned at the engine.match() level (the final fallback that
    # cascade reaches) to prove "Aktiviere {name}" still resolves once that
    # automation-toggle attempt structurally fails to match and falls
    # through, not just that the grammar file alone can match.
    result = engine.match("Aktiviere Gute Nacht", script_entities)
    assert result is not None
    assert result.plan.domain == "script"
    assert result.plan.service == "turn_on"
    assert result.plan.entity_id == "script.gute_nacht"

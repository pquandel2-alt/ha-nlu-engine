"""Cross-domain audit for read-only semantic state questions.

Production code never imports this corpus.  Each case proves a meaningful
domain/state combination and asserts the hard R3 boundary: a question can
produce speech, but never a service-call plan.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.semantic_utterance import SpeechAct, analyse_utterance


@dataclass(frozen=True)
class QueryDomainSpec:
    domain: str
    noun: str
    state: str
    question: str
    expected: str


_DOMAINS = (
    QueryDomainSpec("light", "Licht Atlas", "on", "Ist das Licht Atlas an?", "eingeschaltet"),
    QueryDomainSpec("switch", "Schalter Atlas", "off", "Ist der Schalter Atlas aus?", "ausgeschaltet"),
    QueryDomainSpec("fan", "Ventilator Atlas", "on", "Welchen Zustand hat der Ventilator Atlas?", "eingeschaltet"),
    QueryDomainSpec("cover", "Rollladen Atlas", "open", "Ist der Rollladen Atlas offen?", "geöffnet"),
    QueryDomainSpec("climate", "Heizung Atlas", "heat", "Ist die Heizung Atlas an?", "eingeschaltet"),
    QueryDomainSpec("media_player", "Radio Atlas", "playing", "Ist das Radio Atlas an?", "eingeschaltet"),
    QueryDomainSpec("vacuum", "Saugroboter Atlas", "cleaning", "Läuft der Saugroboter Atlas?", "aktiv"),
    QueryDomainSpec("humidifier", "Luftbefeuchter Atlas", "on", "Ist der Luftbefeuchter Atlas an?", "eingeschaltet"),
    QueryDomainSpec("input_boolean", "Helfer Atlas", "off", "Ist der Helfer Atlas aus?", "ausgeschaltet"),
    QueryDomainSpec("valve", "Ventil Atlas", "closed", "Ist das Ventil Atlas geschlossen?", "geschlossen"),
    QueryDomainSpec("lawn_mower", "Mähroboter Atlas", "mowing", "Was macht der Mähroboter Atlas?", "aktiv"),
)


@pytest.mark.parametrize("spec", _DOMAINS, ids=lambda spec: spec.domain)
def test_named_state_questions_are_read_only(engine, spec: QueryDomainSpec):
    entity = EntitySnapshot(f"{spec.domain}.atlas", spec.noun, spec.domain, spec.state)
    result = engine.match(spec.question, [entity])
    assert result is not None, spec.question
    assert result.plan is None, spec.question
    assert spec.expected in result.response_text


@pytest.mark.parametrize("question", (
    "Ist das Radio Atlas nicht an?",
    "Ist das Licht Atlas nicht an?",
))
def test_negated_copular_questions_are_queries_not_unsafe_commands(engine, question):
    domain = "media_player" if "Radio" in question else "light"
    noun = "Radio Atlas" if domain == "media_player" else "Licht Atlas"
    entity = EntitySnapshot(f"{domain}.atlas", noun, domain, "on")
    assert analyse_utterance(question).speech_act is SpeechAct.QUERY
    result = engine.match(question, [entity])
    assert result is not None
    assert result.plan is None


def test_unsupported_state_domain_is_not_answered_as_an_empty_success(engine):
    camera = EntitySnapshot("camera.einfahrt", "Kamera Einfahrt", "camera", "on")
    assert engine.match("Welche Kamera ist an?", [camera]) is None

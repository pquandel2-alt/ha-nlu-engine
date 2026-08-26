"""Cross-domain audit for read-only semantic state questions.

The broad matrix deliberately combines question verbs with domains for which
they may not make semantic sense. Its job is the hard R3 safety boundary:
every question must stay read-only. Truth quality is tested separately with
only meaningful domain/predicate combinations. Production code never imports
this corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.semantic_utterance import SpeechAct, analyse_utterance


@dataclass(frozen=True)
class QueryDomainSpec:
    domain: str
    noun: str
    nominative: str
    dative: str
    plural: str
    states: tuple[str, str]
    device_class: str | None = None


_DOMAINS = (
    QueryDomainSpec("binary_sensor", "Bewegungsmelder", "der", "dem", "Bewegungsmelder", ("on", "off"), "motion"),
    QueryDomainSpec("cover", "Rollladen", "der", "dem", "Rollläden", ("open", "closed")),
    QueryDomainSpec("light", "Licht", "das", "dem", "Lichter", ("on", "off")),
    QueryDomainSpec("switch", "Schalter", "der", "dem", "Schalter", ("on", "off")),
    QueryDomainSpec("fan", "Ventilator", "der", "dem", "Ventilatoren", ("on", "off")),
    QueryDomainSpec("climate", "Heizung", "die", "der", "Heizungen", ("heat", "off")),
    QueryDomainSpec("media_player", "Radio", "das", "dem", "Radios", ("playing", "off")),
    QueryDomainSpec("vacuum", "Saugroboter", "der", "dem", "Saugroboter", ("cleaning", "docked")),
    QueryDomainSpec("humidifier", "Luftbefeuchter", "der", "dem", "Luftbefeuchter", ("on", "off")),
    QueryDomainSpec("input_boolean", "Helfer", "der", "dem", "Helfer", ("on", "off")),
    QueryDomainSpec("valve", "Ventil", "das", "dem", "Ventile", ("open", "closed")),
    QueryDomainSpec("lawn_mower", "Mähroboter", "der", "dem", "Mähroboter", ("mowing", "docked")),
)

_QUESTION_FORMS = (
    "Ist {nom} {target} {particle}an?",
    "Ist {nom} {target} {particle}nicht an?",
    "Läuft {nom} {target} {particle}?",
    "Spielt {nom} {target} {particle}?",
    "Startet {nom} {target} {particle}?",
    "Stoppt {nom} {target} {particle}?",
    "Was macht {nom} {target} {particle}?",
    "Wie ist der Zustand von {dat} {target} {particle}?",
)
_NAMES = ("Atlas", "Birke", "Citrin", "Dahlie")
_PARTICLES = ("", "gerade ")


@pytest.mark.parametrize("spec", _DOMAINS, ids=lambda spec: spec.domain)
def test_every_question_domain_combination_is_read_only(engine, spec: QueryDomainSpec):
    """Exercise 128 cases per domain (1,536 total) and aggregate failures."""
    entities = [
        EntitySnapshot(
            f"{spec.domain}.matrix_{index}",
            f"{spec.noun} {name}",
            spec.domain,
            spec.states[0],
            device_class=spec.device_class,
        )
        for index, name in enumerate(_NAMES)
    ]
    violations: list[str] = []
    answered = 0
    unanswered = 0
    total = 0
    for question, name, particle, state in product(
        _QUESTION_FORMS, _NAMES, _PARTICLES, spec.states
    ):
        total += 1
        target = f"{spec.noun} {name}"
        sentence = question.format(
            nom=spec.nominative,
            dat=spec.dative,
            plural=spec.plural,
            target=target,
            particle=particle,
        ).replace("  ", " ")
        entity_index = _NAMES.index(name)
        current = entities[entity_index]
        entities[entity_index] = EntitySnapshot(
            current.entity_id,
            current.friendly_name,
            current.domain,
            state,
            device_class=current.device_class,
        )
        result = engine.match(sentence, entities)
        if result is None:
            unanswered += 1
        elif result.plan is not None:
            violations.append(f"PLAN={result.plan.service}: {sentence}")
        else:
            answered += 1
    assert total == 128
    assert not violations, (
        f"{spec.domain}: {answered} beantwortet, {unanswered} nicht beantwortet, "
        f"{len(violations)} R3-Verletzungen\n" + "\n".join(violations[:5])
    )


@pytest.mark.parametrize(
    ("domain", "noun", "state", "question", "expected"),
    (
        ("media_player", "Radio Atlas", "playing", "Spielt das Radio Atlas?", "Ja,"),
        ("media_player", "Radio Atlas", "playing", "Pausiert das Radio Atlas?", "Nein,"),
        ("media_player", "Radio Atlas", "paused", "Pausiert das Radio Atlas?", "Ja,"),
        ("media_player", "Radio Atlas", "paused", "Spielt das Radio Atlas?", "Nein,"),
        ("vacuum", "Saugroboter Atlas", "cleaning", "Läuft der Saugroboter Atlas?", "Ja,"),
        ("vacuum", "Saugroboter Atlas", "docked", "Läuft der Saugroboter Atlas?", "Nein,"),
        ("vacuum", "Saugroboter Atlas", "paused", "Ist der Saugroboter Atlas an?", "nicht sicher"),
        ("vacuum", "Saugroboter Atlas", "cleaning", "Ist der Saugroboter Atlas an?", "Ja,"),
    ),
)
def test_meaningful_state_questions_are_truthful(
    engine, domain: str, noun: str, state: str, question: str, expected: str
):
    entity = EntitySnapshot(f"{domain}.atlas", noun, domain, state)
    result = engine.match(question, [entity])
    assert result is not None, question
    assert result.plan is None, question
    assert expected in result.response_text, result.response_text


@pytest.mark.parametrize(
    ("question", "domain", "noun", "state"),
    (
        ("Spielt das Radio Atlas?", "media_player", "Radio Atlas", "playing"),
        ("Pausiert das Radio Atlas?", "media_player", "Radio Atlas", "paused"),
        ("Startet der Saugroboter Atlas?", "vacuum", "Saugroboter Atlas", "docked"),
        ("Stoppt der Saugroboter Atlas?", "vacuum", "Saugroboter Atlas", "cleaning"),
    ),
)
def test_operation_shaped_questions_never_create_plans(
    engine, question: str, domain: str, noun: str, state: str
):
    entity = EntitySnapshot(f"{domain}.atlas", noun, domain, state)
    assert analyse_utterance(question).speech_act is SpeechAct.QUERY
    result = engine.match(question, [entity])
    assert result is not None
    assert result.plan is None


@pytest.mark.parametrize(
    ("command", "domain", "noun", "state"),
    (
        ("Spiele das Radio Atlas", "media_player", "Radio Atlas", "off"),
        ("Starte den Saugroboter Atlas", "vacuum", "Saugroboter Atlas", "docked"),
        ("Kannst du das Radio Atlas starten?", "media_player", "Radio Atlas", "off"),
        ("Mach das Licht Atlas an", "light", "Licht Atlas", "off"),
        ("Bitte das Licht Atlas an", "light", "Licht Atlas", "off"),
    ),
)
def test_real_commands_remain_executable(
    engine, command: str, domain: str, noun: str, state: str
):
    entity = EntitySnapshot(f"{domain}.atlas", noun, domain, state)
    assert analyse_utterance(command).speech_act is SpeechAct.COMMAND
    result = engine.match(command, [entity])
    assert result is not None
    assert result.plan is not None


def test_unsupported_state_domain_is_not_answered_as_an_empty_success(engine):
    camera = EntitySnapshot("camera.einfahrt", "Kamera Einfahrt", "camera", "on")
    assert engine.match("Welche Kamera ist an?", [camera]) is None


def test_group_verb_questions_report_all_and_matching_entities(engine):
    radios = [
        EntitySnapshot("media_player.atlas", "Radio Atlas", "media_player", "playing"),
        EntitySnapshot("media_player.birke", "Radio Birke", "media_player", "paused"),
    ]

    all_result = engine.match("Spielen die Radios?", radios)
    which_result = engine.match("Welche Radios spielen?", radios)

    assert all_result is not None and all_result.plan is None
    assert "Nein" in all_result.response_text
    assert "Radio Birke" in all_result.response_text
    assert which_result is not None and which_result.plan is None
    assert "Radio Atlas" in which_result.response_text
    assert "Radio Birke" not in which_result.response_text


def test_negated_verb_question_uses_natural_german_correction(engine):
    radio = EntitySnapshot(
        "media_player.atlas", "Radio Atlas", "media_player", "playing"
    )

    result = engine.match("Spielt das Radio Atlas nicht?", [radio])

    assert result is not None and result.plan is None
    assert result.response_text.startswith("Doch,")


def test_past_verb_question_is_not_answered_from_current_state(engine):
    radio = EntitySnapshot(
        "media_player.atlas", "Radio Atlas", "media_player", "playing"
    )

    result = engine.match("Spielte das Radio Atlas gestern?", [radio])

    assert result is None

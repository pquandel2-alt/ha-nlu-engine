from __future__ import annotations

import pytest

from ha_nlu.nlu.semantic_utterance import (
    ClauseRole,
    Modality,
    Polarity,
    SpeechAct,
    analyse_utterance,
)


@pytest.mark.parametrize(
    ("text", "speech_act", "modality", "safe"),
    [
        ("Mach das Licht an", SpeechAct.COMMAND, Modality.DIRECT, True),
        ("Kannst du das Licht einschalten?", SpeechAct.COMMAND, Modality.POLITE, True),
        ("Ich hätte gerne das Licht an", SpeechAct.COMMAND, Modality.WISH, True),
        ("Wie warm ist es?", SpeechAct.QUERY, Modality.DIRECT, False),
        ("Kann man die Tür aufschließen?", SpeechAct.QUERY, Modality.DIRECT, False),
        ("Was passiert, wenn das Fenster offen ist?", SpeechAct.QUERY, Modality.HYPOTHETICAL, False),
        ("Mach vielleicht das Licht an", SpeechAct.COMMAND, Modality.UNCERTAIN, False),
        ("Mach das Licht nicht an", SpeechAct.COMMAND, Modality.DIRECT, False),
    ],
)
def test_classifies_speech_act_modality_and_execution_safety(text, speech_act, modality, safe):
    utterance = analyse_utterance(text)
    assert utterance.speech_act is speech_act
    assert utterance.modality is modality
    assert utterance.safe_to_execute_directly is safe


def test_automation_keeps_action_and_trigger_as_semantic_clauses():
    utterance = analyse_utterance("Benachrichtige mich, wenn das Fenster geöffnet wird")
    assert utterance.speech_act is SpeechAct.AUTOMATION
    assert tuple(clause.role for clause in utterance.clauses) == (
        ClauseRole.ACTION,
        ClauseRole.TRIGGER,
    )
    assert utterance.clauses[0].text == "Benachrichtige mich"
    assert utterance.clauses[1].text == "das Fenster geöffnet wird"


def test_negative_query_is_not_an_executable_negative_command():
    utterance = analyse_utterance("Sind keine Fenster im Erdgeschoss offen?")
    assert utterance.speech_act is SpeechAct.QUERY
    assert utterance.polarity is Polarity.NEGATIVE


@pytest.mark.parametrize(
    "text",
    (
        "Mach das Licht an, wenn es dunkel ist",
        "Wenn es dunkel ist, mach das Licht an",
        "Mach vielleicht das Licht an",
        "Mach das Licht nicht an",
    ),
)
def test_engine_discourse_gate_never_executes_unsafe_direct_command(engine, entities, text):
    assert engine.match(text, entities) is None

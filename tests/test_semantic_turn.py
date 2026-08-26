from __future__ import annotations

import pytest

from ha_nlu.nlu.meaning import (
    CoordinationKind,
    TemporalPerspective,
    analyse_turn,
)
from ha_nlu.nlu.semantic_utterance import Polarity, SpeechAct


@pytest.mark.parametrize(
    ("text", "perspective"),
    (
        ("Läuft das Radio gerade?", TemporalPerspective.CURRENT),
        ("Lief das Radio gestern?", TemporalPerspective.PAST),
        ("Starte das Radio morgen", TemporalPerspective.FUTURE),
        ("Ist das Licht an?", TemporalPerspective.UNSPECIFIED),
    ),
)
def test_turn_exposes_temporal_perspective(text, perspective):
    assert analyse_turn(text).temporal_perspective is perspective


def test_turn_composes_discourse_and_lexical_semantics():
    turn = analyse_turn(
        "Sind alle Radios an, aber das im Wohnzimmer nicht?"
    )

    assert turn.speech_act is SpeechAct.QUERY
    assert turn.polarity is Polarity.NEGATIVE
    assert turn.coordination is CoordinationKind.CONTRASTIVE
    assert turn.semantic_analysis is not None
    assert turn.safe_to_execute_directly is False

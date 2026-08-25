"""Large compositional gate for German command paraphrases.

The cases are generated from independent semantic dimensions.  Production
code never imports this matrix, so adding one shell, particle or target here
cannot teach the parser the expected answer.
"""

from __future__ import annotations

from itertools import product

from ha_nlu.entities import EntitySnapshot


_TARGETS = (
    "Atlas", "Birke", "Citrin", "Dahlie", "Eiche", "Fjord", "Granit", "Hafen",
    "Iris", "Jade", "Komet", "Linde", "Mohn", "Nebel", "Opal", "Perle",
)
_PARTICLES = ("", "mal", "doch", "kurz")
_SHELLS = {
    "turn_on": (
        "Mach {particle} das Licht {name} an",
        "Schalte {particle} das Licht {name} ein",
        "Kannst du {particle} das Licht {name} anmachen?",
        "Wäre es möglich, das Licht {name} {particle} einzuschalten?",
        "Ich hätte gerne das Licht {name} {particle} an",
        "Sorge bitte dafür, dass das Licht {name} {particle} an ist",
        "Das Licht {name} soll {particle} an sein",
        "Bitte das Licht {name} {particle} an",
    ),
    "turn_off": (
        "Mach {particle} das Licht {name} aus",
        "Schalte {particle} das Licht {name} aus",
        "Kannst du {particle} das Licht {name} ausmachen?",
        "Wäre es möglich, das Licht {name} {particle} auszuschalten?",
        "Ich hätte gerne das Licht {name} {particle} aus",
        "Sorge bitte dafür, dass das Licht {name} {particle} aus ist",
        "Das Licht {name} soll {particle} aus sein",
        "Bitte das Licht {name} {particle} aus",
    ),
}


def test_at_least_one_thousand_composed_paraphrases_have_the_same_meaning(engine):
    entities = [
        EntitySnapshot(
            f"light.matrix_{index}",
            f"Licht {name}",
            "light",
            "off",
            capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
        )
        for index, name in enumerate(_TARGETS)
    ]
    cases = tuple(
        (name, service, shell.format(name=name, particle=particle).replace("  ", " "))
        for name, service, particle in product(_TARGETS, _SHELLS, _PARTICLES)
        for shell in _SHELLS[service]
    )
    assert len(cases) == 1024

    for name, service, sentence in cases:
        result = engine.match(sentence, entities)
        assert result is not None, sentence
        assert result.plan is not None, sentence
        assert result.plan.service == service, sentence
        assert result.plan.entity_id == f"light.matrix_{_TARGETS.index(name)}", sentence

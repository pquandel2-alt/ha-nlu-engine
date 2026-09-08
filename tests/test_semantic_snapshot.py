from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.semantic_interpreter import SemanticInterpreter
from ha_nlu.nlu.semantic_snapshot import build_semantic_snapshot


def test_snapshot_covers_every_understanding_stage(engine):
    entities = [
        EntitySnapshot(
            "light.kueche", "Küchenlicht", "light", "on",
            capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
        )
    ]
    text = "Mach bitte das Küchenlicht aus."
    document = analyse_language(text, entities)
    interpreted = SemanticInterpreter.interpret(document, entities)
    outcome = engine.understand(text, entities, document=document)

    snapshot = build_semantic_snapshot(document, interpreted, outcome)

    assert snapshot["input"] == text
    assert snapshot["structure"]["clauses"]
    assert snapshot["graph"] is not None
    assert snapshot["candidates"]
    assert snapshot["selected"]
    assert snapshot["resolved_entities"] == ("light.kueche",)
    assert snapshot["outcome"] == {
        "kind": "command",
        "reason": None,
        "actionable": True,
        "route": "HassTurnOff",
    }

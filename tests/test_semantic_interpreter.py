from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.parser import ParseResult
from ha_nlu.nlu.semantic_interpreter import SemanticInterpreter
from ha_nlu.nlu.understanding import EvidenceKind


ENTITIES = [
    EntitySnapshot(
        "light.kueche",
        "Küchenlicht",
        "light",
        "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    )
]


def test_interpreter_composes_candidate_and_safe_parse_from_one_document():
    document = analyse_language("Wäre es möglich, das Küchenlicht einzuschalten?", ENTITIES)

    result = SemanticInterpreter.interpret(document, ENTITIES)

    assert result.candidates
    assert any(candidate.complete for candidate in result.candidates)
    assert isinstance(result.parse_result, ParseResult)
    assert result.parse_result.frame.intent == "HassTurnOn"


def test_compiler_resolution_completes_candidate_without_duplicate_registry_scan():
    document = analyse_language("Mach das Küchenlicht an", ENTITIES)

    result = SemanticInterpreter.interpret(
        document, ENTITIES, compile_result=True, resolve_registry=False
    )

    complete = [candidate for candidate in result.candidates if candidate.complete]
    assert len(complete) == 1
    assert complete[0].missing_slots == ()
    assert complete[0].slots["entities"] == ("light.kueche",)


def test_phonetic_variant_is_visible_but_never_compiled_for_execution():
    document = analyse_language(
        "Mach das Küchenlict an", ENTITIES, include_phonetic=True
    )

    result = SemanticInterpreter.interpret(document, ENTITIES)

    phonetic = [
        evidence
        for candidate in result.candidates
        for evidence in candidate.evidence
        if evidence.kind is EvidenceKind.PHONETIC
    ]
    assert phonetic
    assert result.parse_result is None


def test_conflicting_actions_produce_no_complete_candidate():
    document = analyse_language("Mach das Küchenlicht an und aus", ENTITIES)

    result = SemanticInterpreter.interpret(document, ENTITIES)

    assert all(not candidate.complete for candidate in result.candidates)
    assert any("action" in candidate.conflicts for candidate in result.candidates)

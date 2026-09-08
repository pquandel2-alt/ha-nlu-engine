from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.parser import ParseResult
from ha_nlu.nlu.semantic_interpreter import SemanticInterpreter
from ha_nlu.nlu.semantic_graph import SemanticEdgeKind, SemanticNodeKind
from ha_nlu.nlu.understanding import EvidenceKind


ENTITIES = [
    EntitySnapshot(
        "light.decke", "Deckenlampe", "light", "on",
        area_id="living_room", area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "light.tisch", "Tischlampe", "light", "off",
        area_id="living_room", area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "light.steh", "Stehlampe", "light", "on",
        area_id="living_room", area_name="Wohnzimmer",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
]


def test_relative_state_filter_and_exclusion_project_to_existing_compiler():
    text = (
        "Mach im Wohnzimmer die Lampen aus, die noch an sind, "
        "außer der Stehlampe."
    )
    result = SemanticInterpreter.interpret(analyse_language(text, ENTITIES), ENTITIES)

    assert isinstance(result.parse_result, ParseResult)
    assert [entity.entity_id for entity in result.parse_result.resolved_entities] == [
        "light.decke"
    ]
    assert result.parse_result.frame.intent == "HassTurnOff"
    assert result.parse_result.frame.parameters["state_filter"] == "on"
    assert result.parse_result.frame.parameters["excluded"] == ("Stehlampe",)
    assert result.parse_result.frame.parameters["excluded_entity_ids"] == (
        "light.steh",
    )
    assert result.parse_result.frame.source_text == text
    graph = result.parse_result.frame.semantic_graph
    assert graph is not None
    excluded_nodes = {
        edge.target
        for edge in graph.edges
        if edge.kind is SemanticEdgeKind.EXCLUDE
    }
    assert any(
        node.node_id in excluded_nodes
        and node.kind is SemanticNodeKind.ENTITY
        and node.value == "light.steh"
        for node in graph.nodes
    )


def test_relative_state_filter_does_not_turn_state_into_opposite_action():
    result = SemanticInterpreter.interpret(
        analyse_language("Mach alle Lampen aus, die noch an sind.", ENTITIES),
        ENTITIES,
    )

    assert isinstance(result.parse_result, ParseResult)
    assert result.parse_result.frame.intent == "HassTurnOff"
    assert {entity.entity_id for entity in result.parse_result.resolved_entities} == {
        "light.decke", "light.steh"
    }


def test_unknown_relative_predicate_remains_non_executable():
    result = SemanticInterpreter.interpret(
        analyse_language("Mach alle Lampen aus, die gemütlich sind.", ENTITIES),
        ENTITIES,
    )

    assert result.parse_result is None
    assert all(not candidate.complete for candidate in result.candidates)


def test_structural_projection_reaches_normal_validator_and_service_mapper(engine):
    text = (
        "Mach im Wohnzimmer die Lampen aus, die noch an sind, "
        "außer der Stehlampe."
    )
    outcome = engine.understand(text, ENTITIES)

    assert outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan is not None
    assert outcome.payload.frame is not None
    assert outcome.payload.frame.intent == "HassTurnOff"
    assert outcome.payload.plan.service == "turn_off"
    assert outcome.payload.plan.entity_id == "light.decke"
    assert outcome.evidence
    assert any(item.kind is EvidenceKind.STRUCTURE for item in outcome.evidence)


def test_scoped_only_not_projects_as_exclusion(engine):
    outcome = engine.understand(
        "Mach alle Lampen aus, nur die Stehlampe nicht.", ENTITIES
    )

    assert outcome.actionable
    assert outcome.payload is not None
    assert outcome.payload.plan is not None
    assert set(outcome.payload.plan.entity_id) == {
        "light.decke", "light.tisch"
    }


def test_predicate_negation_still_never_executes(engine):
    outcome = engine.understand("Mach die Stehlampe nicht aus.", ENTITIES)

    assert not outcome.actionable

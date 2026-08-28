from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.language_frontend import analyse_language
from ha_nlu.nlu.parser import ClarificationRequest, ParseResult
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

MEDIA_ENTITIES = [
    EntitySnapshot(
        "media_player.wohnzimmer",
        "Medienplayer Wohnzimmer",
        "media_player",
        "playing",
        aliases=("Radio Wohnzimmer",),
    )
]

VACUUM_ENTITIES = [
    EntitySnapshot("vacuum.atlas", "Saugroboter Atlas", "vacuum", "docked")
]

MEASUREMENT_ENTITIES = [
    EntitySnapshot(
        "sensor.wohnzimmer_temp",
        "Wohnzimmer Temperatur",
        "sensor",
        "21.5",
        area_id="wohnzimmer",
        area_name="Wohnzimmer",
        floor_id="erdgeschoss",
        floor_name="Erdgeschoss",
        device_class="temperature",
        unit="°C",
    ),
    EntitySnapshot(
        "sensor.kueche_temp",
        "Küche Temperatur",
        "sensor",
        "22.5",
        area_id="kueche",
        area_name="Küche",
        floor_id="erdgeschoss",
        floor_name="Erdgeschoss",
        device_class="temperature",
        unit="°C",
    ),
]

STATE_ENTITIES = [
    EntitySnapshot("light.kueche", "Küchenlicht", "light", "off"),
    EntitySnapshot(
        "binary_sensor.bad_fenster",
        "Badezimmerfenster",
        "binary_sensor",
        "on",
        device_class="window",
    ),
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
    # The original surface may now identify one bounded registry typo, but
    # it remains non-executable until the user confirms the offered entity.
    assert isinstance(result.parse_result, ClarificationRequest)
    assert result.parse_result.candidates == (ENTITIES[0],)


def test_conflicting_actions_produce_no_complete_candidate():
    document = analyse_language("Mach das Küchenlicht an und aus", ENTITIES)

    result = SemanticInterpreter.interpret(document, ENTITIES)

    assert all(not candidate.complete for candidate in result.candidates)
    assert any("action" in candidate.conflicts for candidate in result.candidates)


def test_domain_invalid_particle_does_not_create_action_conflict():
    document = analyse_language(
        "Wäre es möglich, den Saugroboter Atlas zu starten?", VACUUM_ENTITIES
    )

    result = SemanticInterpreter.interpret(document, VACUUM_ENTITIES)

    assert isinstance(result.parse_result, ParseResult)
    assert result.parse_result.frame.intent == "HassVacuumStart"
    assert any(candidate.complete for candidate in result.candidates)
    assert all("action" not in candidate.conflicts for candidate in result.candidates)


def test_actions_with_same_domain_intent_are_not_a_semantic_conflict():
    document = analyse_language(
        "Ich hätte gerne auf dem Medienplayer Wohnzimmer die Wiedergabe gestartet",
        MEDIA_ENTITIES,
    )

    result = SemanticInterpreter.interpret(document, MEDIA_ENTITIES)

    assert isinstance(result.parse_result, ParseResult)
    assert result.parse_result.frame.intent == "HassMediaPlay"
    assert any(candidate.complete for candidate in result.candidates)


def test_separable_pause_verb_is_a_command_not_a_statement():
    document = analyse_language(
        "Halte die Wiedergabe auf dem Medienplayer Wohnzimmer an", MEDIA_ENTITIES
    )

    result = SemanticInterpreter.interpret(document, MEDIA_ENTITIES)

    assert document.utterance.speech_act.name == "COMMAND"
    assert isinstance(result.parse_result, ParseResult)
    assert result.parse_result.frame.intent == "HassMediaPause"


def test_measurement_query_compiles_from_property_and_location_in_free_order():
    document = analyse_language(
        "Im Erdgeschoss aktuell die Temperatur wie viel?", MEASUREMENT_ENTITIES
    )

    result = SemanticInterpreter.interpret(document, MEASUREMENT_ENTITIES)

    assert isinstance(result.parse_result, ParseResult)
    assert result.parse_result.frame.intent == "HassLocationPropertyQuery"
    assert {entity.entity_id for entity in result.parse_result.resolved_entities} == {
        "sensor.wohnzimmer_temp",
        "sensor.kueche_temp",
    }
    assert any(candidate.complete for candidate in result.candidates)


def test_verb_state_query_is_a_grounded_read_only_semantic_result():
    document = analyse_language("Spielt das Radio Wohnzimmer?", MEDIA_ENTITIES)

    result = SemanticInterpreter.interpret(document, MEDIA_ENTITIES)

    assert isinstance(result.parse_result, ParseResult)
    assert result.parse_result.response_text is not None
    assert result.parse_result.response_text.startswith("Ja,")
    assert result.parse_result.context_predicate == "playing"
    assert result.parse_result.frame.action.name == "QUERY"


def test_named_copular_state_query_resolves_only_the_explicit_entity():
    document = analyse_language("Ist das Badezimmerfenster offen?", STATE_ENTITIES)

    result = SemanticInterpreter.interpret(document, STATE_ENTITIES)

    assert isinstance(result.parse_result, ParseResult)
    assert result.parse_result.frame.intent == "HassCheckState"
    assert [entity.entity_id for entity in result.parse_result.resolved_entities] == [
        "binary_sensor.bad_fenster"
    ]


def test_shared_predicate_named_targets_form_one_atomic_compositional_plan():
    document = analyse_language(
        "Schalte Küchenlicht und Flurlicht aus",
        [
            EntitySnapshot("light.kueche", "Küchenlicht", "light", "on"),
            EntitySnapshot("light.flur", "Flurlicht", "light", "on"),
        ],
    )

    result = SemanticInterpreter.interpret(
        document,
        [
            EntitySnapshot("light.kueche", "Küchenlicht", "light", "on"),
            EntitySnapshot("light.flur", "Flurlicht", "light", "on"),
        ],
    )

    assert result.compositional_plan is not None
    assert {entity.entity_id for entity in result.compositional_plan.targets} == {
        "light.kueche",
        "light.flur",
    }

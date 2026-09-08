from ha_nlu.nlu.german_structure import (
    ArgumentRole,
    ClauseKind,
    NegationKind,
    StructuralRelationKind,
    WordClass,
)
from ha_nlu.nlu.language_frontend import analyse_language


def test_relative_filter_and_exclusion_have_separate_scopes():
    document = analyse_language(
        "Mach im Wohnzimmer die Lampen aus, die noch an sind, außer der Stehlampe."
    )

    assert [clause.kind for clause in document.structure.clauses] == [
        ClauseKind.MAIN,
        ClauseKind.RELATIVE,
        ClauseKind.EXCLUSION,
    ]
    assert [relation.kind for relation in document.structure.relations] == [
        StructuralRelationKind.MODIFIES,
        StructuralRelationKind.EXCEPT,
    ]


def test_nested_condition_and_comparison_preserve_logical_connectors():
    document = analyse_language(
        "Wenn draußen kälter ist als drinnen und jemand zuhause ist, mach die Heizung aus."
    )

    assert document.structure.clauses[0].kind is ClauseKind.CONDITION
    assert document.structure.clauses[-1].kind is ClauseKind.MAIN
    assert any(
        relation.kind is StructuralRelationKind.IF
        and relation.target_clause == document.structure.clauses[-1].clause_id
        for relation in document.structure.relations
    )
    assert any(
        relation.kind is StructuralRelationKind.AND
        for relation in document.structure.relations
    )


def test_temporal_connectors_are_not_flattened_into_generic_conditions():
    document = analyse_language(
        "Falls niemand zuhause ist, nachdem die Haustür geschlossen wurde, schalte das Licht aus."
    )

    kinds = {relation.kind for relation in document.structure.relations}
    assert StructuralRelationKind.AFTER in kinds


def test_repair_sequence_is_explicit():
    document = analyse_language("Stell die Heizung auf 22, nein 21 Grad.")

    assert any(
        relation.kind is StructuralRelationKind.REPLACES
        for relation in document.structure.relations
    )
    assert document.structure.clauses[-1].kind is ClauseKind.REPAIR


def test_negation_has_local_clause_scope():
    document = analyse_language("Mach alle Lichter aus, nur das Küchenlicht nicht.")

    assert len(document.structure.negations) == 1
    negation = document.structure.negations[0]
    assert negation.kind is NegationKind.PREDICATE
    assert negation.clause_id == document.structure.clauses[-1].clause_id


def test_structure_retains_source_offsets():
    text = "Öffne das Fenster, nachdem die Heizung ausgegangen ist."
    document = analyse_language(text)

    for clause in document.structure.clauses:
        assert text[clause.char_start:clause.char_end]


def test_structural_features_capture_arguments_and_separable_particle():
    document = analyse_language("Mach im Wohnzimmer das Licht aus.")

    assert any(
        feature.word_class is WordClass.PREPOSITION
        and feature.lemma == "im"
        for feature in document.structure.token_features
    )
    assert any(
        argument.role is ArgumentRole.LOCATIVE
        for argument in document.structure.clauses[0].arguments
    )
    assert document.structure.particle_links
    assert document.structure.particle_links[0].combined_lemma.startswith("aus")


def test_pronoun_is_retained_as_reference_argument():
    document = analyse_language("Mach es dort zwei Grad wärmer.")

    assert any(
        argument.role is ArgumentRole.REFERENCE
        for argument in document.structure.clauses[0].arguments
    )

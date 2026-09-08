import pytest

from ha_nlu.nlu.primitives import SemanticAction
from ha_nlu.nlu.semantic_aliases import (
    ConfirmedSemanticAliasStore,
    SemanticAliasDraft,
    SemanticAliasKind,
    SemanticAliasMeaning,
)


def test_semantic_and_routine_aliases_are_typed_and_confirmed():
    store = ConfirmedSemanticAliasStore()
    cozy = SemanticAliasDraft(
        "gemütlich",
        SemanticAliasKind.SEMANTIC,
        meaning=SemanticAliasMeaning(
            SemanticAction.ADJUST,
            (("property", "brightness"), ("step_percent", -20)),
        ),
    )
    movie = SemanticAliasDraft(
        "Filmabend", SemanticAliasKind.ROUTINE,
        routine_entity_id="scene.movie_night",
    )

    with pytest.raises(ValueError, match="bestätigt"):
        store.add(cozy, confirmed=False)
    store.add(cozy, confirmed=True)
    store.add(movie, confirmed=True)
    assert store.lookup("GEMÜTLICH") == cozy
    assert store.lookup("filmabend") == movie


def test_alias_kind_cannot_mix_missing_meaning_with_routine():
    with pytest.raises(ValueError, match="Bedeutung"):
        SemanticAliasDraft("gemütlich", SemanticAliasKind.SEMANTIC)

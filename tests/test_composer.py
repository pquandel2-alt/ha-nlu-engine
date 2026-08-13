"""Semantic Composer (V6.4): composes SemanticFrame primitive fields
(property, quantity) from a bag of already-tokenized words, using
nlu/lexicon.py's word->candidate tables. Only property/quantity are
composed - action/direction/degree have no lexicon candidate table yet
(see composer.py's own docstring)."""

from __future__ import annotations

from ha_nlu.nlu.composer import ComposedPrimitives, SemanticComposer
from ha_nlu.nlu.primitives import SemanticProperty, SemanticQuantity


def test_compose_single_property_word():
    result = SemanticComposer.compose(["rot"])
    assert result == ComposedPrimitives(property=SemanticProperty.COLOR, quantity=None)


def test_compose_single_quantity_word():
    result = SemanticComposer.compose(["beide"])
    assert result == ComposedPrimitives(property=None, quantity=SemanticQuantity.exactly(2))


def test_compose_combines_property_and_quantity_from_different_words():
    """Worked example from the plan: "die beiden Lampen" combines the
    quantifier word "beide" with (elsewhere-resolved) TARGET=LIGHT; here we
    combine "beide" with a color word to show composition across words."""
    result = SemanticComposer.compose(["beide", "rot"])
    assert result == ComposedPrimitives(
        property=SemanticProperty.COLOR, quantity=SemanticQuantity.exactly(2)
    )


def test_compose_ignores_unrecognized_words():
    result = SemanticComposer.compose(["die", "Lampen", "im", "Wohnzimmer"])
    assert result == ComposedPrimitives(property=None, quantity=None)


def test_compose_empty_words_returns_empty_primitives():
    assert SemanticComposer.compose([]) == ComposedPrimitives()


def test_compose_first_match_wins_for_same_primitive():
    """"rot" (-> COLOR) and "kaltweiß" (-> COLOR_TEMPERATURE) both map to
    the ``property`` primitive; the first word in the list wins rather than
    the last one overwriting it."""
    result = SemanticComposer.compose(["rot", "kaltweiß"])
    assert result.property is SemanticProperty.COLOR

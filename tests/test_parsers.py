"""Phase 2 (v2 plan): sentence-matching + resolution moved out of engine.py
into dedicated IntentParser implementations (parsers.py). These tests
exercise the parsers directly (bypassing NluEngine.match()'s routing) to
pin down that they conform to the IntentParser Protocol and return
ParseResult/None independently of how engine.py builds a ServiceCallPlan
from that result."""

from __future__ import annotations

from ha_nlu.nlu.parser import IntentParser, ParseContext, ParseResult
from ha_nlu.parsers import PercentageParser, QuantifierParser, SingleTargetParser


def test_parsers_conform_to_intent_parser_protocol(engine):
    assert isinstance(engine._single_parser, IntentParser)
    assert isinstance(engine._quantifier_parser, IntentParser)
    assert isinstance(engine._percentage_parser, IntentParser)
    assert isinstance(engine._single_parser, SingleTargetParser)
    assert isinstance(engine._quantifier_parser, QuantifierParser)
    assert isinstance(engine._percentage_parser, PercentageParser)


def test_single_target_parser_returns_parse_result(engine, entities):
    context = ParseContext(entities=entities)
    result = engine._single_parser.parse("Mach Treppenlicht an", context)
    assert isinstance(result, ParseResult)
    assert result.frame.intent == "HassTurnOn"
    assert result.resolved_entities == [next(e for e in entities if e.entity_id == "light.treppen_licht_gruppe")]


def test_single_target_parser_returns_none_on_no_match(engine, entities):
    context = ParseContext(entities=entities)
    assert engine._single_parser.parse("Das ergibt keinen Sinn", context) is None


def test_quantifier_parser_returns_none_without_quantifier_wording(engine, quantifier_entities):
    # QuantifierParser's grammar requires a {quantifier} slot - plain "fahre
    # Rollladen hoch" (no "alle"/"beide") must not match here, it belongs to
    # SingleTargetParser's grammar instead.
    context = ParseContext(entities=quantifier_entities)
    assert engine._quantifier_parser.parse("fahre Rollladen hoch", context) is None


def test_percentage_parser_returns_none_for_unsupported_domain(engine, entities):
    context = ParseContext(entities=entities)
    # "Garagentor" resolves (switch domain), but switches have no percent
    # semantics - PERCENT_INTENTS has no entry for "switch".
    assert engine._percentage_parser.parse("mach den Garagentor auf 50 Prozent", context) is None

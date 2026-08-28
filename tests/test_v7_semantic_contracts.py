"""Generated semantic contracts, not a catalogue of one-off sentences.

Each contract defines one meaning. Independent surface transformations must
preserve its executable result across domains and registry names.
"""

from __future__ import annotations

from itertools import product

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.understanding import UnderstandingKind


ENTITIES = [
    EntitySnapshot(
        "light.nord", "Nordlicht", "light", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    ),
    EntitySnapshot(
        "switch.garten", "Gartenschalter", "switch", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "fan.turm", "Turmventilator", "fan", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
    ),
    EntitySnapshot(
        "climate.buero", "Büroheizung", "climate", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}),
    ),
    EntitySnapshot(
        "cover.buero", "Bürorollo", "cover", "closed",
        capabilities=frozenset({"POSITION"}),
    ),
    EntitySnapshot("media_player.kueche", "Küchenradio", "media_player", "paused"),
    EntitySnapshot("vacuum.atlas", "Saugroboter Atlas", "vacuum", "docked"),
]


POWER_CONTRACTS = (
    ("Nordlicht", "light.nord", "an", "anmachen", "turn_on"),
    ("Nordlicht", "light.nord", "aus", "ausmachen", "turn_off"),
    ("Gartenschalter", "switch.garten", "an", "anmachen", "turn_on"),
    ("Gartenschalter", "switch.garten", "aus", "ausmachen", "turn_off"),
    ("Turmventilator", "fan.turm", "an", "anmachen", "turn_on"),
    ("Turmventilator", "fan.turm", "aus", "ausmachen", "turn_off"),
    ("Büroheizung", "climate.buero", "an", "anmachen", "turn_on"),
    ("Büroheizung", "climate.buero", "aus", "ausmachen", "turn_off"),
)

POWER_SHELLS = (
    "Mach {particle} {name} {state}",
    "Kannst du {particle} {name} {infinitive}?",
    "Bitte {name} {state}",
    "{name} soll {state} sein",
)


def _plan(engine, sentence):
    outcome = engine.understand(sentence, ENTITIES)
    assert outcome.kind is UnderstandingKind.COMMAND, sentence
    assert outcome.payload is not None and outcome.payload.plan is not None, sentence
    return outcome.payload.plan


def test_power_meanings_survive_independent_surface_transformations(engine):
    cases = (
        (contract, shell, particle)
        for contract, shell, particle in product(
            POWER_CONTRACTS, POWER_SHELLS, ("", "mal", "doch", "kurz")
        )
    )

    for (name, entity_id, state, infinitive, service), shell, particle in cases:
        sentence = shell.format(
            name=name, state=state, infinitive=infinitive, particle=particle
        ).replace("  ", " ")
        plan = _plan(engine, sentence)
        assert plan.entity_id == entity_id, sentence
        assert plan.service == service, sentence


def test_operation_families_share_registry_and_safety_resolution(engine):
    contracts = (
        ("Öffne bitte Bürorollo", "cover.buero", "open_cover"),
        ("Fahre das Bürorollo hoch", "cover.buero", "open_cover"),
        ("Schließe bitte Bürorollo", "cover.buero", "close_cover"),
        ("Fahre das Bürorollo herunter", "cover.buero", "close_cover"),
        ("Spiele das Küchenradio", "media_player.kueche", "media_play"),
        ("Pausiere bitte das Küchenradio", "media_player.kueche", "media_pause"),
        ("Stoppe das Küchenradio", "media_player.kueche", "media_stop"),
        ("Starte den Saugroboter Atlas", "vacuum.atlas", "start"),
        ("Stoppe bitte den Saugroboter Atlas", "vacuum.atlas", "stop"),
    )

    for sentence, entity_id, service in contracts:
        expected = _plan(engine, sentence)
        for transformed in (
            sentence,
            f"Also, {sentence}",
            f"Ähm, {sentence}",
            f"{sentence}!",
        ):
            plan = _plan(engine, transformed)
            assert plan.entity_id == entity_id, transformed
            assert plan.service == service, transformed
            assert (plan.domain, plan.service, plan.entity_id, plan.data) == (
                expected.domain,
                expected.service,
                expected.entity_id,
                expected.data,
            )


def test_safety_transformations_never_preserve_actionability(engine):
    unsafe = (
        "Mach das Nordlicht nicht an",
        "Vielleicht machst du das Nordlicht an",
        "Wenn es dunkel ist, mach das Nordlicht an",
        "Was wäre, wenn du das Nordlicht anmachst?",
    )

    for sentence in unsafe:
        outcome = engine.understand(sentence, ENTITIES)
        assert not outcome.actionable, sentence
        assert outcome.payload is None, sentence

"""Cross-domain audit for compositional German device commands.

Unlike the intensive light-only matrix, this suite varies the HA domain and
uses operation-specific, grammatically valid sentence shells.  It follows the
same direct-command routing order as the live conversation layer: extended
device router first, general NLU engine second.  Production code never imports
this audit corpus.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pytest

from ha_nlu.device_control import match_device_control
from ha_nlu.entities import EntitySnapshot


@dataclass(frozen=True)
class OperationSpec:
    service: str
    shells: tuple[str, ...]


@dataclass(frozen=True)
class DomainSpec:
    domain: str
    noun: str
    nominative: str
    accusative: str
    capabilities: frozenset[str]
    attributes: dict
    operations: tuple[OperationSpec, ...]


_ON = OperationSpec("turn_on", (
    "Schalte {particle} {acc} {target} ein",
    "Mach {particle} {acc} {target} an",
    "Kannst du {particle} {acc} {target} anmachen?",
    "Wäre es möglich, {acc} {target} {particle} einzuschalten?",
    "Ich hätte gerne {acc} {target} {particle} an",
    "Sorge bitte dafür, dass {nom} {target} {particle} an ist",
    "{nom} {target} soll {particle} an sein",
    "Bitte {acc} {target} {particle} an",
))
_OFF = OperationSpec("turn_off", (
    "Schalte {particle} {acc} {target} aus",
    "Mach {particle} {acc} {target} aus",
    "Kannst du {particle} {acc} {target} ausmachen?",
    "Wäre es möglich, {acc} {target} {particle} auszuschalten?",
    "Ich hätte gerne {acc} {target} {particle} aus",
    "Sorge bitte dafür, dass {nom} {target} {particle} aus ist",
    "{nom} {target} soll {particle} aus sein",
    "Bitte {acc} {target} {particle} aus",
))
_OPEN = OperationSpec("open_cover", (
    "Öffne {particle} {acc} {target}",
    "Fahre {particle} {acc} {target} hoch",
    "Kannst du {particle} {acc} {target} öffnen?",
    "Wäre es möglich, {acc} {target} {particle} zu öffnen?",
    "Ich hätte gerne {acc} {target} {particle} offen",
    "Sorge bitte dafür, dass {nom} {target} {particle} offen ist",
    "{nom} {target} soll {particle} offen sein",
    "Bitte {acc} {target} {particle} hochfahren",
))
_CLOSE = OperationSpec("close_cover", (
    "Schließe {particle} {acc} {target}",
    "Fahre {particle} {acc} {target} runter",
    "Kannst du {particle} {acc} {target} schließen?",
    "Wäre es möglich, {acc} {target} {particle} zu schließen?",
    "Ich hätte gerne {acc} {target} {particle} geschlossen",
    "Sorge bitte dafür, dass {nom} {target} {particle} geschlossen ist",
    "{nom} {target} soll {particle} geschlossen sein",
    "Bitte {acc} {target} {particle} herunterfahren",
))
_PLAY = OperationSpec("media_play", (
    "Starte {particle} die Wiedergabe auf {acc} {target}",
    "Spiele {particle} auf {acc} {target} weiter",
    "Kannst du {particle} auf {acc} {target} die Wiedergabe starten?",
    "Wäre es möglich, auf {acc} {target} {particle} weiterzuspielen?",
    "Ich hätte gerne auf {acc} {target} {particle} die Wiedergabe gestartet",
    "Sorge bitte dafür, dass {nom} {target} {particle} weiterspielt",
    "{nom} {target} soll {particle} die Wiedergabe starten",
    "Bitte auf {acc} {target} {particle} weiterspielen",
))
_PAUSE = OperationSpec("media_pause", (
    "Pausiere {particle} die Wiedergabe auf {acc} {target}",
    "Halte {particle} die Wiedergabe auf {acc} {target} an",
    "Kannst du {particle} auf {acc} {target} die Wiedergabe pausieren?",
    "Wäre es möglich, auf {acc} {target} {particle} zu pausieren?",
    "Ich hätte gerne die Wiedergabe auf {acc} {target} {particle} pausiert",
    "Sorge bitte dafür, dass {nom} {target} {particle} pausiert ist",
    "{nom} {target} soll {particle} die Wiedergabe pausieren",
    "Bitte auf {acc} {target} {particle} pausieren",
))
_START = OperationSpec("start", (
    "Starte {particle} {acc} {target}",
    "Lass {particle} {acc} {target} starten",
    "Kannst du {particle} {acc} {target} starten?",
    "Wäre es möglich, {acc} {target} {particle} zu starten?",
    "Ich hätte gerne {acc} {target} {particle} gestartet",
    "Sorge bitte dafür, dass {nom} {target} {particle} startet",
    "{nom} {target} soll {particle} starten",
    "Bitte {acc} {target} {particle} starten",
))
_STOP = OperationSpec("stop", (
    "Stoppe {particle} {acc} {target}",
    "Lass {particle} {acc} {target} stoppen",
    "Kannst du {particle} {acc} {target} stoppen?",
    "Wäre es möglich, {acc} {target} {particle} zu stoppen?",
    "Ich hätte gerne {acc} {target} {particle} gestoppt",
    "Sorge bitte dafür, dass {nom} {target} {particle} stoppt",
    "{nom} {target} soll {particle} stoppen",
    "Bitte {acc} {target} {particle} stoppen",
))
_OPEN_VALVE = OperationSpec("open_valve", (
    "Öffne {particle} {acc} {target}",
    "Mach {particle} {acc} {target} auf",
    "Kannst du {particle} {acc} {target} öffnen?",
    "Wäre es möglich, {acc} {target} {particle} zu öffnen?",
    "Ich hätte gerne {acc} {target} {particle} offen",
    "Sorge bitte dafür, dass {nom} {target} {particle} offen ist",
    "{nom} {target} soll {particle} offen sein",
    "Bitte {acc} {target} {particle} öffnen",
))
_CLOSE_VALVE = OperationSpec("close_valve", (
    "Schließe {particle} {acc} {target}",
    "Mach {particle} {acc} {target} zu",
    "Kannst du {particle} {acc} {target} schließen?",
    "Wäre es möglich, {acc} {target} {particle} zu schließen?",
    "Ich hätte gerne {acc} {target} {particle} geschlossen",
    "Sorge bitte dafür, dass {nom} {target} {particle} geschlossen ist",
    "{nom} {target} soll {particle} geschlossen sein",
    "Bitte {acc} {target} {particle} schließen",
))

_DOMAINS = (
    DomainSpec("light", "Licht", "das", "das", frozenset({"TURN_ON", "TURN_OFF"}), {}, (_ON, _OFF)),
    DomainSpec("switch", "Schalter", "der", "den", frozenset({"TURN_ON", "TURN_OFF"}), {}, (_ON, _OFF)),
    DomainSpec("fan", "Ventilator", "der", "den", frozenset({"TURN_ON", "TURN_OFF"}), {}, (_ON, _OFF)),
    DomainSpec("cover", "Rollladen", "der", "den", frozenset({"POSITION"}), {}, (_OPEN, _CLOSE)),
    DomainSpec("climate", "Heizung", "die", "die", frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}), {"temperature": 21}, (_ON, _OFF)),
    DomainSpec("media_player", "Medienplayer", "der", "den", frozenset(), {}, (_PLAY, _PAUSE)),
    DomainSpec("vacuum", "Saugroboter", "der", "den", frozenset(), {}, (_START, _STOP)),
    DomainSpec("humidifier", "Luftbefeuchter", "der", "den", frozenset({"TURN_ON", "TURN_OFF"}), {}, (_ON, _OFF)),
    DomainSpec("valve", "Ventil", "das", "das", frozenset({"OPEN", "CLOSE"}), {"supported_features": 3}, (_OPEN_VALVE, _CLOSE_VALVE)),
)

_NAMES = ("Atlas", "Birke", "Citrin", "Dahlie")
_PARTICLES = ("", "mal", "doch", "kurz")


def _assert_domain_matrix(engine, spec: DomainSpec, *, live_route: bool) -> None:
    entities = [
        EntitySnapshot(
            f"{spec.domain}.matrix_{index}", f"{spec.noun} {name}", spec.domain, "off",
            capabilities=spec.capabilities, attributes=spec.attributes,
        )
        for index, name in enumerate(_NAMES)
    ]
    failures: list[str] = []
    total = 0
    for name, particle, operation in product(_NAMES, _PARTICLES, spec.operations):
        target = f"{spec.noun} {name}"
        for shell in operation.shells:
            total += 1
            sentence = shell.format(
                particle=particle, nom=spec.nominative, acc=spec.accusative, target=target,
            ).replace("  ", " ")
            semantic_result = engine.match(sentence, entities)
            result = (
                match_device_control(sentence, entities) or semantic_result
                if live_route else semantic_result
            )
            plan = getattr(result, "plan", None)
            expected_id = f"{spec.domain}.matrix_{_NAMES.index(name)}"
            if result is None:
                failures.append(f"NO_MATCH: {sentence}")
            elif plan is None:
                failures.append(f"NO_PLAN: {sentence}")
            elif plan.service != operation.service:
                failures.append(f"SERVICE {plan.service!r}: {sentence}")
            elif plan.entity_id != expected_id:
                failures.append(f"ENTITY {plan.entity_id!r}: {sentence}")
    assert not failures, (
        f"{spec.domain} ({'live' if live_route else 'compiler'}): "
        f"{total - len(failures)}/{total} bestanden, "
        f"{len(failures)} fehlgeschlagen\n" + "\n".join(failures[:3])
    )


@pytest.mark.parametrize("spec", _DOMAINS, ids=lambda spec: spec.domain)
def test_semantic_compiler_domain_matrix(engine, spec: DomainSpec):
    _assert_domain_matrix(engine, spec, live_route=False)


@pytest.mark.parametrize("spec", _DOMAINS, ids=lambda spec: spec.domain)
def test_live_domain_compositionality_matrix(engine, spec: DomainSpec):
    _assert_domain_matrix(engine, spec, live_route=True)


def test_valve_capability_is_a_hard_execution_gate(engine):
    entity = EntitySnapshot("valve.garden", "Ventil Garten", "valve", "closed")
    assert engine.match("Bitte das Ventil Garten öffnen", [entity]) is None

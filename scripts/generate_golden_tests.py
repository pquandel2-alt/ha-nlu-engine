"""Generator for tests/golden/*.json (v2 plan Phase 20, "Golden Tests").

Rather than hand-computing expected values (error-prone across ~100+ cases),
this script runs every candidate sentence through the REAL engine, asserts
success/failure matches the author's intent for that sentence, and
serializes the actual output as a pinned regression fixture. tests/golden_
fixtures.py's GOLDEN_ENTITIES is the shared entity set - test_golden.py
resolves names against the exact same list on replay.

Run with: python scripts/generate_golden_tests.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "custom_components"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from ha_nlu.engine import NluEngine  # noqa: E402
from ha_nlu.service_call import ServiceCallPlan  # noqa: E402
from golden_fixtures import GOLDEN_ENTITIES  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "tests" / "golden"

# Each category maps to a list of sentences that MUST match. Negative cases
# (must NOT match) live in their own "negative" category, handled separately
# below since they carry no expected plan/response.
CATEGORIES: dict[str, list[str]] = {
    "commands": [
        "Mach das Wohnzimmerlicht an",
        "Mach das Wohnzimmerlicht aus",
        "Schalte das Küchenlicht ein",
        "Küchenlicht ausschalten",
        "Kannst du das Flurlicht anmachen?",
        "Bitte das Flurlicht aus",
        "schalte die Steckdose Büro um",
        "Steckdose Büro umschalten",
        "toggle das Flurlicht",
        "mach den Ventilator an",
        "schalte den Ventilator aus",
        "mach die Heizung Wohnzimmer an",
        "schalte die Einfache Heizung aus",
        "Mach das Küchenlicht an",
        "Schalte das Flurlicht ein",
        "Flurlicht ausschalten",
        "Kannst du die Steckdose Büro anmachen?",
        "Bitte das Wohnzimmerlicht an",
        "schalte das Wohnzimmerlicht um",
        "Wohnzimmerlicht umschalten",
        "toggle die Steckdose Büro",
        "Kannst du den Ventilator anmachen?",
        "Bitte den Ventilator aus",
        "kannst du die Heizung Wohnzimmer anmachen",
        "bitte die Einfache Heizung aus",
        "mach die Steckdose Büro an",
        "schalte das Küchenlicht aus",
    ],
    "cover_open_close": [
        "mach den Rollladen Büro ganz auf",
        "öffne den Rollladen Büro",
        "fahre den Rollladen Büro hoch",
        "bitte den Rollladen Büro hochfahren",
        "kannst du den Rollladen Büro öffnen",
        "mach den Rollladen Schlafzimmer zu",
        "schließe den Rollladen Schlafzimmer",
        "fahre den Rollladen Schlafzimmer runter",
        "bitte den Rollladen Schlafzimmer runterfahren",
        "kannst du den Rollladen Schlafzimmer schließen",
        "mach den Rollladen Schlafzimmer ganz auf",
        "öffne den Rollladen Schlafzimmer",
        "fahre den Rollladen Schlafzimmer hoch",
        "bitte den Rollladen Büro hoch",
        "bitte den Rollladen Schlafzimmer hoch",
        "mach den Rollladen Büro zu",
        "schließe den Rollladen Büro",
        "fahre den Rollladen Büro runter",
        "bitte den Rollladen Büro runter",
        "bitte den Rollladen Schlafzimmer runter",
        "kannst du die Rolllade Poleraum links öffnen",
        "kannst du die Rolllade Poleraum rechts schließen",
    ],
    "percentage": [
        "fahre den Rollladen Büro auf 30 Prozent runter",
        "fahre den Rollladen Büro auf 70 Prozent hoch",
        "kannst du den Rollladen Schlafzimmer auf 50 Prozent stellen",
        "den Rollladen Büro auf 0 Prozent fahren",
        "den Rollladen Schlafzimmer auf 100 Prozent dimmen",
        "mach das Wohnzimmerlicht auf 50 Prozent",
        "mach das Küchenlicht auf 20 Prozent",
        "kannst du das Wohnzimmerlicht auf 80 Prozent dimmen",
        "bitte das Küchenlicht auf 1 Prozent einstellen",
        "stelle das Wohnzimmerlicht auf 100 Prozent",
        "fahre den Rollladen Schlafzimmer auf 45 Prozent runter",
        "fahre den Rollladen Schlafzimmer auf 90 Prozent hoch",
        "den Rollladen Büro auf 60 Prozent stellen",
        "den Rollladen Schlafzimmer auf 15 Prozent fahren",
        "mach das Küchenlicht auf 100 Prozent",
        "mach das Wohnzimmerlicht auf 0 Prozent",
        "kannst du das Küchenlicht auf 75 Prozent dimmen",
        "bitte das Wohnzimmerlicht auf 33 Prozent einstellen",
        "stelle das Küchenlicht auf 10 Prozent",
        "setze den Rollladen Büro auf 25 Prozent",
    ],
    "quantifiers": [
        "fahre alle Rollläden hoch",
        "fahre alle Rollläden runter",
        "mach alle Lichter an",
        "mach alle Lichter aus",
        "schalte alle Schalter aus",
        "fahre beide Rollläden im Poleraum hoch",
        "fahre beide Rollläden im Poleraum runter",
        "öffne alle Rollläden im Poleraum",
        "schließe alle Rollläden im Poleraum",
        "schalte alle Schalter ein",
        "kannst du alle Lichter anmachen",
        "bitte alle Lichter aus",
        "öffne alle Rollläden",
        "schließe alle Rollläden",
        "mach alle Rollläden auf",
        "mach alle Rollläden zu",
        "schalte alle Lichter um",
        # "außer {name}" exclusion (v2 plan V2.9 quantifier scope) - not
        # previously covered by any golden case despite being a distinct
        # grammar branch in quantifiers/*.yaml.
        "mach alle Lichter an außer dem Wohnzimmerlicht",
        "fahre alle Rollläden hoch außer dem Rollladen Büro",
        "schließe alle Rollläden außer der Rolllade Poleraum links",
        "fahre die beiden Rollläden im Poleraum hoch",
    ],
    "light_extended": [
        "mach das Wohnzimmerlicht um 20 Prozent heller",
        "kannst du das Wohnzimmerlicht heller machen",
        "mach das Wohnzimmerlicht um 30 Prozent dunkler",
        "bitte das Wohnzimmerlicht dunkler machen",
        "mach das Wohnzimmerlicht rot",
        "stelle das Wohnzimmerlicht auf blau",
        "kannst du das Wohnzimmerlicht grün machen",
        "mach das Wohnzimmerlicht warmweiß",
        "stelle das Wohnzimmerlicht auf kaltweiß",
        "mach das Küchenlicht heller",
        "bitte das Küchenlicht heller machen",
        "mach das Küchenlicht dunkler",
        "kannst du das Küchenlicht dunkler machen",
        "mach das Wohnzimmerlicht gelb",
        "stelle das Wohnzimmerlicht auf orange",
        "mach das Wohnzimmerlicht lila",
        "stelle das Wohnzimmerlicht auf violett",
        "mach das Wohnzimmerlicht weiß",
        "kannst du das Wohnzimmerlicht pink machen",
        "mach das Wohnzimmerlicht rosa",
        "stelle das Wohnzimmerlicht auf türkis",
        "kannst du das Wohnzimmerlicht cyan machen",
        "kannst du das Wohnzimmerlicht warmweiß machen",
    ],
    "fan_extended": [
        "stelle den Ventilator auf Stufe 3",
        "mach den Ventilator auf Stufe 1",
        "kannst du den Ventilator auf Stufe 5 stellen",
        "mach den Ventilator schneller",
        "bitte den Ventilator schneller machen",
        "mach den Ventilator langsamer",
        "bitte den Ventilator langsamer machen",
        "stelle den Ventilator auf Stufe 2",
        "mach den Ventilator auf Stufe 4",
        "kannst du den Ventilator auf Stufe 1 stellen",
        "kannst du den Ventilator schneller machen",
        "kannst du den Ventilator langsamer machen",
    ],
    "climate_extended": [
        "stelle die Heizung Wohnzimmer auf 21 Grad",
        "mach die Heizung Wohnzimmer auf 19 Grad",
        "kannst du die Heizung Wohnzimmer auf 22 Grad stellen",
        "mach die Heizung Wohnzimmer wärmer",
        "kannst du die Heizung Wohnzimmer wärmer machen",
        "erhöhe die Temperatur von der Heizung Wohnzimmer",
        "mach die Heizung Wohnzimmer kälter",
        "senke die Temperatur bei der Heizung Wohnzimmer",
        "stelle die Heizung Wohnzimmer auf 18 Grad",
        "mach die Heizung Wohnzimmer auf 24 Grad",
        "kannst du die Heizung Wohnzimmer auf 16 Grad stellen",
        "bitte die Heizung Wohnzimmer wärmer machen",
        "bitte die Heizung Wohnzimmer kälter machen",
        "erhöhe die Temperatur an der Heizung Wohnzimmer",
        "senke die Temperatur von der Heizung Wohnzimmer",
    ],
    "queries": [
        "wie hoch ist die Außentemperatur?",
        "wie ist die Außentemperatur",
        "wie hoch ist die Luftfeuchtigkeit Bad",
        "wie hell ist das Wohnzimmerlicht",
        "wie ist das Wohnzimmerlicht",
        "wie warm ist die Außentemperatur",
        "wie ist die Luftfeuchtigkeit Bad",
        "wie hell ist das Küchenlicht",
        "wie ist das Küchenlicht",
        "wie hell ist das Flurlicht",
        "wie ist die Waschmaschine?",
        "wie viel Strom verbraucht die Waschmaschine?",
        "wie viel Energie verbraucht der Trockner?",
        "wie ist die Fensterkontakt Batterie?",
    ],
    # V2.14 gap closure: SingleTargetParser's tied-name outcome (Phase 25,
    # "Clarification") never had golden coverage even though it's a core
    # "never guess" behaviour, not an edge case - see test_clarification.py
    # for the same mechanism covered unit-level.
    "ambiguity": [
        "Mach das Testlicht an",
        "Mach das Testlicht aus",
        "Schalte das Testlicht ein",
    ],
}

# Sentences that must NOT match (kein ServiceCall, "nicht verstanden").
NEGATIVE_SENTENCES: list[str] = [
    "blubb schnarch wuppdi",
    "Mach irgendwas.",
    "Mach das Licht.",
    "Mach das Wohnzimmerlicht lila leuchten tanzen",
    "Mach die Küchenlampe blau",  # light.kueche has no COLOR capability
    "stelle den Rollladen Büro auf 200 Prozent",  # out of range, RangeSlotList rejects
    "mach beide Lichter an",  # 3 lights with no area set -> "beide" needs exactly 2 hits
    "fahre beide Rollläden im Büro hoch",  # "Büro" isn't a registered area_name on any entity
    "stelle die Einfache Heizung auf 21 Grad",  # no TEMPERATURE capability
    "mach den Ventilator lila",
    "wie hoch ist der Rollladen Büro",  # cover is not a queryable domain
    "Mach das Kellerlicht an",  # unknown entity name
    "fahre die Rolllade im Keller hoch",  # unresolvable area
    "mach das Licht auf 150 Prozent",  # out of range percentage
    "stelle die Steckdose Büro auf 50 Prozent",  # switch has no PERCENT-capable domain mapping
    "mach beide Ventilatoren an",  # v2 plan Phase 21 example: "beide" but only 1 fan exists
    "schalte beide Schalter aus",  # same rule, switch domain (only 1 switch entity)
]


def _plan_to_dict(plan: ServiceCallPlan | None) -> dict | None:
    return asdict(plan) if plan is not None else None


def generate() -> None:
    engine = NluEngine()
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    total = 0

    for category, sentences in CATEGORIES.items():
        cases = []
        for text in sentences:
            result = engine.match(text, GOLDEN_ENTITIES)
            assert result is not None, f"[{category}] expected a match for: {text!r}"
            cases.append(
                {
                    "text": text,
                    "expect_match": True,
                    "plan": _plan_to_dict(result.plan),
                    "response_text": result.response_text,
                }
            )
        out_path = GOLDEN_DIR / f"{category}.json"
        out_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        total += len(cases)
        print(f"{category}: {len(cases)} cases -> {out_path.relative_to(REPO_ROOT)}")

    negative_cases = []
    for text in NEGATIVE_SENTENCES:
        result = engine.match(text, GOLDEN_ENTITIES)
        assert result is None, f"[negative] expected NO match for: {text!r}, got {result!r}"
        negative_cases.append({"text": text, "expect_match": False})
    out_path = GOLDEN_DIR / "negative.json"
    out_path.write_text(json.dumps(negative_cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    total += len(negative_cases)
    print(f"negative: {len(negative_cases)} cases -> {out_path.relative_to(REPO_ROOT)}")

    print(f"\nTotal: {total} golden cases generated.")


if __name__ == "__main__":
    generate()

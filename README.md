# HA NLU Engine

Eigenständiger, deterministischer Conversation Agent für Home Assistants
**Assist** (Settings → Sprachassistenten → Assist → Conversation Agent) -
kein LLM, kein Fallback, kein Fuzzy-Scoring.

## Wie es matcht

1. [hassil](https://github.com/home-assistant/hassil) (HA Cores eigene
   Satzmuster-Bibliothek) matcht die Satzstruktur gegen `intents/de/*.yaml`.
2. Der erkannte `{name}`-Slot wird gegen die aktuell für Assist freigegebenen
   Entities aufgelöst - exakter Treffer, sonst ein eindeutiger
   Teilstring-Treffer. Mehrdeutige oder unbekannte Namen zählen als kein
   Treffer.
3. Die aufgelöste Entity muss zur erlaubten Domain des Intents passen
   (`service_call.py`).

Nur wenn alle drei Schritte greifen, wird ein Service-Call ausgeführt. Sonst
antwortet die Engine mit einer festen "Das habe ich nicht verstanden."
Es gibt in v1 keine Weiterleitung an ein LLM.

## v1-Scope

- Licht/Schalter/Fan: an, aus, umschalten
- Rollladen: öffnen, schließen

## Installation

`custom_components/ha_nlu/` in die Home-Assistant-Config kopieren (manuell
oder als HACS Custom Repository), Home Assistant neu starten, Integration
"HA NLU Engine" hinzufügen, danach in den Assist-Einstellungen als
Conversation Agent auswählen.

## Tests

```bash
pip install hassil pytest
pytest tests/
```

"""HA-free vocabulary and intent registry for compositional device commands.

This module describes reusable nouns and operations, never complete sentence
templates.  Both discourse detection and the semantic compiler consume these
constants so adding a domain does not require copying word lists between
routers.  Concrete Home Assistant service calls remain in ``service_call``.
"""

from __future__ import annotations


DOMAIN_EXPRESSIONS: dict[str, tuple[str, ...]] = {
    "light": (r"licht(?:er)?", r"lamp(?:e|en)", r"leucht(?:e|en)", r"beleuchtung"),
    "switch": (r"schalter", r"steckdos(?:e|en)"),
    "cover": (r"rol{1,3}[aä]d(?:e|en)", r"rollos?", r"jalousie(?:n)?"),
    "fan": (r"ventilator(?:en)?", r"lüfter"),
    "climate": (r"heizung(?:en)?", r"thermostat(?:e)?"),
    "script": (r"skript(?:e)?",),
    "media_player": (r"medienplayer", r"media[ -]?player", r"lautsprecher", r"radio", r"fernseher"),
    "vacuum": (r"saugroboter", r"staubsauger(?:roboter)?", r"sauger"),
    "humidifier": (r"luftbefeuchter", r"befeuchter"),
    "water_heater": (r"warmwasser(?:bereiter)?", r"boiler", r"wasserheizer"),
    "input_boolean": (r"helfer", r"modus", r"modi"),
    "number": (r"wert", r"regler"),
    "input_number": (r"zahlenhelfer", r"wert", r"regler"),
    "select": (r"auswahl", r"profil", r"programm"),
    "button": (r"taste", r"knopf", r"button"),
    "valve": (r"ventil(?:e)?",),
    "lawn_mower": (r"mähroboter", r"maehroboter", r"rasenmäher", r"rasenmaeher"),
    "scene": (r"szene(?:n)?",),
    "camera": (r"kamera(?:s)?",),
}

# Normalized literal forms for registry-name scoring and area/floor group
# resolution. Regex inflections above serve lexical scanning; these terms
# serve exact token matching without either consumer owning another list.
DOMAIN_WORDS: dict[str, tuple[str, ...]] = {
    "light": ("licht", "lichter", "lampe", "lampen", "leuchte", "leuchten", "beleuchtung"),
    "switch": ("schalter", "steckdose", "steckdosen"),
    "cover": ("rollladen", "rollläden", "rolladen", "rolläden", "rollo", "rollos", "jalousie", "jalousien"),
    "fan": ("ventilator", "ventilatoren", "lüfter"),
    "climate": ("heizung", "heizungen", "thermostat", "thermostate"),
    "script": ("skript", "skripte"),
    "media_player": ("medienplayer", "media player", "lautsprecher", "player", "radio", "fernseher"),
    "vacuum": ("saugroboter", "staubsauger", "staubsaugerroboter", "sauger"),
    "humidifier": ("luftbefeuchter", "befeuchter"),
    "water_heater": ("warmwasser", "warmwasserbereiter", "boiler", "wasserheizer"),
    "input_boolean": ("helfer", "modus", "modi"),
    "number": ("wert", "regler"),
    "input_number": ("zahlenhelfer", "wert", "regler", "helfer"),
    "select": ("auswahl", "profil", "programm"),
    "button": ("taste", "knopf", "button"),
    "valve": ("ventil", "ventile"),
    "lawn_mower": ("mähroboter", "maehroboter", "mäher", "maeher", "rasenmäher", "rasenmaeher"),
    "scene": ("szene", "szenen"),
    "camera": ("kamera", "kameras"),
}

# Literal resolver words that are deliberately broader than the lexical
# scanner expressions.  Keeping the small difference explicit turns future
# drift into a test failure instead of silently growing two vocabularies.
DOMAIN_WORD_ONLY_TERMS: dict[str, frozenset[str]] = {
    "media_player": frozenset({"player"}),  # useful registry-name shorthand
    "input_number": frozenset({"helfer"}),  # HA UI commonly calls input_number a helper
    "lawn_mower": frozenset({"mäher", "maeher"}),  # natural short noun for name resolution
}


COMMAND_MARKER_EXPRESSIONS: tuple[str, ...] = (
    r"(?:an|aus|zu)mach(?:e|en|st|t)?", r"(?:ein|aus)schalt(?:e|en|st|t)?",
    r"mach(?:e|en|st|t)?", r"schalt(?:e|en|st|t)?", r"stell(?:e|en|st|t)?",
    r"setz(?:e|en)?", r"fahr(?:e|en)?", r"gefahren", r"hochfahr(?:e|en)?",
    r"runterfahr(?:e|en)?", r"herunterfahr(?:e|en)?", r"eingeschaltet",
    r"ausgeschaltet", r"öffn(?:e|en|est|et)?", r"schließ(?:e|en|est|et)?",
    r"dreh(?:e|en)?", r"lass(?:e|en)?", r"aktivier(?:e|en|st|t)?",
    r"deaktivier(?:e|en|st|t)?", r"start(?:e|en|est|et)?", r"gestartet",
    r"spiel(?:e|en|st|t)?", r"weiterspiel(?:e|en|st|t)?", r"pausier(?:e|en|st|t)?",
    r"stopp(?:e|en|st|t)?", r"führ(?:e|en)?", r"ausführen",
)


ACTION_EXPRESSIONS: dict[str, tuple[str, ...]] = {
    "open": (
        r"hoch", r"oben", r"offen", r"hochfahr(?:e|en)?", r"hochgefahren",
        r"öffn(?:e|en|est|et)?", r"mach(?:e|en|st|t)?(?:\s+\w+){1,8}\s+auf",
    ),
    "close": (
        r"runter", r"herunter", r"nach\s+unten", r"runterfahr(?:e|en)?",
        r"herunterfahr(?:e|en)?", r"geschlossen", r"schließ(?:e|en|est|et)?",
        r"zumach(?:e|en|st|t)?", r"mach(?:e|en|st|t)?\s+(?:es\s+)?zu",
        r"zu(?!\s+öffn)",
    ),
    "turn_on": (
        r"an", r"ein", r"anmach(?:e|en|st|t)?", r"einschalt(?:e|en|st|t)?",
        r"eingeschaltet", r"aktivier(?:e|en|st|t)?",
    ),
    "turn_off": (
        r"aus", r"ausmach(?:e|en|st|t)?", r"ausschalt(?:e|en|st|t)?",
        r"ausgeschaltet", r"deaktivier(?:e|en|st|t)?",
    ),
    "toggle": (r"umschalt(?:e|en)?", r"toggle"),
    "start": (r"start(?:e|en|est|et)?", r"gestartet"),
    "play": (
        r"spiel(?:e|en|st|t)?", r"weiter", r"weiter(?:zu)?spiel(?:e|en|st|t)?",
        r"wiedergabe\s+gestartet",
    ),
    "pause": (r"pausier(?:e|en|st|t)?", r"pausiert", r"halt(?:e|en|st|t)?\s+.*?\s+an"),
    "stop": (r"stopp(?:e|en|st|t)?", r"gestoppt"),
}


# A domain/action pair has exactly one executable meaning.  Unsupported
# combinations are absent and therefore cannot be guessed by the compiler.
INTENT_BY_DOMAIN_ACTION: dict[tuple[str, str], str] = {
    **{(domain, "turn_on"): "HassTurnOn" for domain in ("light", "switch", "fan", "climate", "humidifier", "input_boolean")},
    **{(domain, "turn_off"): "HassTurnOff" for domain in ("light", "switch", "fan", "climate", "humidifier", "input_boolean")},
    **{(domain, "toggle"): "HassToggle" for domain in ("light", "switch", "fan", "climate", "humidifier", "input_boolean")},
    ("cover", "open"): "HassOpenCover",
    ("cover", "close"): "HassCloseCover",
    ("script", "start"): "HassRunScript",
    ("scene", "start"): "HassActivateScene",
    ("scene", "turn_on"): "HassActivateScene",
    ("media_player", "start"): "HassMediaPlay",
    ("media_player", "play"): "HassMediaPlay",
    ("media_player", "pause"): "HassMediaPause",
    ("media_player", "stop"): "HassMediaStop",
    ("vacuum", "start"): "HassVacuumStart",
    ("vacuum", "stop"): "HassVacuumStop",
    ("valve", "open"): "HassOpenValve",
    ("valve", "close"): "HassCloseValve",
}


def regex_union(expressions: tuple[str, ...] | list[str]) -> str:
    """Return one non-capturing regex alternative for module-level reuse."""
    return r"(?:" + "|".join(expressions) + r")"

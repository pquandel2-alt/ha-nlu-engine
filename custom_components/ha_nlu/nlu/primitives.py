"""Semantic Primitives (V6 architecture plan, V6.1): a small, immutable,
type-safe shared vocabulary of semantic building blocks. Meaning is meant to
be composed from these reusable pieces ("mach...an" / "schalte...ein" /
"lass...an" -> a shared ``SemanticAction.TURN_ON``; "Licht" / "Lampe" /
"Beleuchtung" -> a shared LIGHT target) instead of one rule per sentence -
see ``docs/architecture-v6.md`` section 1 for the full rationale.

Kept free of Home Assistant and hassil imports, same boundary as
``nlu/frame.py`` and ``nlu/capabilities.py`` - this is pure vocabulary/typing,
reusable by any future parser/composer implementation. No pipeline logic
lives here: nothing in this module is wired into ``engine.py``/``parsers.py``/
``frame.py`` yet (V6.1 is preparatory; the Semantic Composer that will
actually consume this vocabulary is V6.4, a later step).

Every enum value below is backed by a real, already-existing intent/
capability/parameter in this codebase (cross-checked against
``service_call.py``'s ``INTENTS``/``PERCENT_INTENTS``/``QUERY_INTENTS``/
``FAN_EXTENDED_INTENTS``/``CLIMATE_EXTENDED_INTENTS``/``LIGHT_EXTENDED_INTENTS``
and ``parsers.py``'s parser classes) - nothing here is speculative vocabulary
invented ahead of demonstrated need, with the single documented exception of
``SemanticDegree`` (see its own docstring).

Primitives from the V6.1 plan list (Entity, Target, Action, Property, State,
Location, Area, Floor, Quantity, Comparison, Direction, Degree, Reference,
Condition, TemporalExpression, Capability, Query, Command) that already have
a clear existing counterpart elsewhere in this codebase are deliberately
**not** redefined here, to avoid two competing types for the same concept:

- **Entity**   -> ``entities.EntitySnapshot`` (outside ``nlu/``: this is the
  one place the hass-free boundary is intentionally crossed, since a
  resolved entity inherently carries live HA state).
- **Target**   -> ``nlu.frame.TargetReference``.
- **Area**     -> ``nlu.frame.AreaReference``.
- **Comparison** -> ``nlu.frame.Comparison``.
- **TemporalExpression** -> ``nlu.frame.TemporalExpression``.
- **Capability** -> ``nlu.capabilities.Capability``.
- **Quantity/Quantifier** -> ``nlu.frame.Quantifier`` is the *current*
  ``kind="all"/"both"/"count"`` implementation. ``SemanticQuantity`` below
  is the richer V6.1-planned replacement (adds SOME/EXCLUDE, which
  ``Quantifier`` has no room for) - it does not replace ``Quantifier`` yet;
  that migration is Wave 2b's (Semantic Frame extension) job.
- **State**    -> ``nlu.semantic_state.SemanticState`` (OPEN/CLOSED/ON/OFF/
  UNKNOWN).
- **Query** (the *kind of value* a query asks for) -> ``nlu.query.QueryType``
  (STATE/TEMPERATURE/HUMIDITY/BRIGHTNESS/POWER/ENERGY/BATTERY). The
  *operation* sense of "Query" (as opposed to "Command") is instead covered
  by ``SemanticAction.QUERY`` below, mirroring how ``service_call.py``
  already separates ``INTENTS``/``PERCENT_INTENTS``/extended-intent dicts
  (commands) from ``QUERY_INTENTS`` (queries).

Primitives from the V6.1 plan list that have **no** existing counterpart yet
(Location as a generic concept beyond the fixed "oben"/"unten" ``{level}``
slot, Floor as a ``FloorReference`` - only ``floors.py``'s HA-coupled
``FloorSnapshot`` exists today, Reference/pronoun resolution, Condition) are
intentionally **not** invented here either: designing those types is Wave 2b's
job (``SemanticFrame`` extension), not this preparatory vocabulary step -
inventing them now without the Frame/Composer work that gives them meaning
would risk guessing a shape that doesn't fit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class SemanticAction(Enum):
    """What a command wants to do, or that it's a read instead of a write.

    Grounded in ``service_call.py``'s real intent tables:
    TURN_ON <- ``HassTurnOn`` (also ``HassTurnOnOthers``, mapped back to
    ``HassTurnOn`` by ``parsers.py``'s ``_OTHERS_INTENT_MAP``); TURN_OFF <-
    ``HassTurnOff``/``HassTurnOffOthers``; TOGGLE <- ``HassToggle``; OPEN <-
    ``HassOpenCover``; CLOSE <- ``HassCloseCover``; SET <- the *absolute*-value
    intents (``HassSetPercentage`` cover/light branch of ``PERCENT_INTENTS``,
    ``HassClimateSetTemperature``, ``HassFanSetSpeed``, ``HassLightSetColor``,
    ``HassLightSetColorTemp``); ADJUST <- the *relative*-step intents
    (``HassLightBrighten``/``HassLightDim``, ``HassFanIncreaseSpeed``/
    ``HassFanDecreaseSpeed``, ``HassClimateIncreaseTemperature``/
    ``HassClimateDecreaseTemperature``); QUERY <- every entry in
    ``QUERY_INTENTS`` (``HassGetState``, ``HassQueryComparison``,
    ``HassStateQuery``, ``HassCheckState``, ``HassExistsQuery``).

    TOGGLE is real (``HassToggle`` has its own ``IntentSpec``) but wasn't in
    the plan's example list - added here since the "identify what parsers.py
    actually produces" instruction takes precedence over the example list.
    """

    TURN_ON = auto()
    TURN_OFF = auto()
    TOGGLE = auto()
    OPEN = auto()
    CLOSE = auto()
    SET = auto()
    ADJUST = auto()
    QUERY = auto()


class SemanticProperty(Enum):
    """Which measurable/settable aspect of an entity a command/query targets.

    BRIGHTNESS/COLOR/COLOR_TEMPERATURE/TEMPERATURE/POSITION/POWER/ENERGY are
    the plan's own example set, and all seven are real: BRIGHTNESS <-
    ``Capability.BRIGHTNESS`` + ``QueryType.BRIGHTNESS`` +
    ``HassLightBrighten``/``HassLightDim``/light branch of
    ``PERCENT_INTENTS``; COLOR <- ``Capability.COLOR`` +
    ``HassLightSetColor``; COLOR_TEMPERATURE <-
    ``Capability.COLOR_TEMPERATURE`` + ``HassLightSetColorTemp``; TEMPERATURE
    <- ``Capability.TEMPERATURE`` + ``QueryType.TEMPERATURE`` +
    ``HassClimateSetTemperature``/``HassClimateIncreaseTemperature``/
    ``HassClimateDecreaseTemperature``; POSITION <- ``Capability.POSITION`` +
    cover branch of ``PERCENT_INTENTS``; POWER <- ``Capability.POWER`` +
    ``QueryType.POWER`` (sensor device_class "power"); ENERGY <-
    ``Capability.ENERGY`` + ``QueryType.ENERGY`` (sensor device_class
    "energy").

    HUMIDITY/FAN_SPEED/BATTERY are added beyond the plan's example list
    because they are equally real, not invented: HUMIDITY <-
    ``Capability.HUMIDITY`` + ``QueryType.HUMIDITY`` (sensor device_class
    "humidity", the plan text itself calls out checking for this); FAN_SPEED
    <- ``Capability.FAN_SPEED`` + ``HassFanSetSpeed``/
    ``HassFanIncreaseSpeed``/``HassFanDecreaseSpeed``; BATTERY <-
    ``QueryType.BATTERY`` (sensor device_class "battery" - query-only today,
    no command sets a battery level, which is physically correct).
    """

    BRIGHTNESS = auto()
    COLOR = auto()
    COLOR_TEMPERATURE = auto()
    TEMPERATURE = auto()
    POSITION = auto()
    POWER = auto()
    ENERGY = auto()
    HUMIDITY = auto()
    FAN_SPEED = auto()
    BATTERY = auto()


class SemanticDirection(Enum):
    """Which way an ADJUST action moves a property.

    Grounded in the three relative-step intent pairs: INCREASE <-
    ``HassLightBrighten``/``HassFanIncreaseSpeed``/
    ``HassClimateIncreaseTemperature``; DECREASE <-
    ``HassLightDim``/``HassFanDecreaseSpeed``/
    ``HassClimateDecreaseTemperature``.
    """

    INCREASE = auto()
    DECREASE = auto()


class SemanticDegree(Enum):
    """How much an ADJUST action should move a property - SLIGHT/MODERATE/
    LARGE, per the plan's own worked example ("...etwas dunkler." ->
    ``degree=SLIGHT``, V6.2 plan text, Brain node
    ``52ae9a3a-c380-4a26-9a49-ce8b1db94367``).

    Unlike every other primitive in this module, this one is **not** yet
    backed by an observable distinction in the current codebase: today
    ``nlu/normalize.py`` strips "etwas"/"ein bisschen" (and "mal"/"doch"/
    "kurz") as meaningless filler *before* any parser sees the sentence
    (see its own docstring - "etwas heller" == "heller"), and
    ``parsers.py``'s ``LightExtendedParser`` always steps by the same fixed
    ``_DEFAULT_DIMMING_STEP_PERCENT = 10`` regardless of wording. So there is
    currently no lexicon evidence to point ``SLIGHT``/``MODERATE``/``LARGE``
    at - they are included because the plan explicitly requires this
    primitive and gives a worked example, but wiring an actual degree
    *distinction* (e.g. un-stripping "etwas"/"stark" and giving them
    different step sizes) is out of scope here; see this module's own
    docstring and the OPEN ISSUES in the Wave 2a report for the follow-up.
    """

    SLIGHT = auto()
    MODERATE = auto()
    LARGE = auto()


class SemanticQuantityKind(Enum):
    ALL = auto()
    EXACTLY = auto()
    SOME = auto()
    EXCLUDE = auto()


@dataclass(frozen=True)
class SemanticQuantity:
    """How many of the matched candidates a command/query applies to - the
    V6.1-planned successor to ``nlu.frame.Quantifier`` (see this module's
    top docstring for why ``Quantifier`` isn't touched/replaced here).

    ALL/EXACTLY(n) are grounded 1:1 in ``Quantifier``'s current
    ``kind="all"``/``kind="count", value=n`` (``lexicon._QUANTIFIER_SLOT_LIST``'s
    "alle"/"nur" -> "all", ``lexicon._COUNT_SLOT_LIST``'s "zwei".."zehn", and
    "beide" -> ``EXACTLY(2)`` per ``Quantifier``'s own docstring). SOME/EXCLUDE
    have no lexicon/parser counterpart yet anywhere in this codebase - the
    plan lists them as part of the target vocabulary (``SemanticQuantity{ALL,
    EXACTLY(n), SOME, EXCLUDE(...)}``) so the type accommodates them now,
    but no parser produces them today; see OPEN ISSUES in the Wave 2a report.

    Construct via the classmethods below rather than the raw constructor -
    mirrors the plan's own ``ALL``/``EXACTLY(n)``/``SOME``/``EXCLUDE(...)``
    call-site shape.
    """

    kind: SemanticQuantityKind
    count: int | None = None
    excluded: tuple[str, ...] = ()

    @classmethod
    def all(cls) -> "SemanticQuantity":
        return cls(SemanticQuantityKind.ALL)

    @classmethod
    def exactly(cls, count: int) -> "SemanticQuantity":
        return cls(SemanticQuantityKind.EXACTLY, count=count)

    @classmethod
    def some(cls) -> "SemanticQuantity":
        return cls(SemanticQuantityKind.SOME)

    @classmethod
    def exclude(cls, *excluded: str) -> "SemanticQuantity":
        return cls(SemanticQuantityKind.EXCLUDE, excluded=tuple(excluded))


class NumericUnit(Enum):
    """The unit a ``NumericValue`` (V6 architecture plan, V6.16, "Number
    Normalization") is expressed in - grounded 1:1 in the three real
    ``RangeType``/unit contexts ``parsers.py`` already uses for property
    values: PERCENT <- ``PercentageParser``/``LightExtendedParser``'s/
    ``ComparisonQueryParser``'s ``RangeType.PERCENTAGE`` "percent" slots;
    CELSIUS <- ``ClimateExtendedParser``'s "temperature" slot (a plain
    ``RangeType.NUMBER`` whose unit is Celsius by the sentence's own
    grammar, e.g. "X Grad"); LEVEL <- ``FanExtendedParser``'s "level" slot
    ("Stufe X", ``RangeType.NUMBER`` 1-10). ``RangeType.NUMBER`` slots that
    are not property values at all (``TemporalParser``'s "amount"/"hour",
    minutes/clock-hour rather than a settable property) are deliberately
    excluded - those stay ``TemporalExpression``'s job (frame.py), not this
    primitive's.
    """

    PERCENT = auto()
    CELSIUS = auto()
    LEVEL = auto()


@dataclass(frozen=True)
class NumericValue:
    """A number together with its unit - the plan's own worked examples
    ("50"/"50%"/"50 Prozent"/"fünfzig Prozent" -> ``NumericValue(50,
    PERCENT)``; "21 Grad"/"21°"/"einundzwanzig Grad" -> ``NumericValue(21,
    CELSIUS)``; "Stufe 3"/"Stufe drei" -> ``NumericValue(3, LEVEL)``).

    The surface-form normalization these examples describe (symbol vs. word,
    digit vs. spelled-out number) is already fully handled *before* this
    type would ever be constructed: ``nlu/normalize.py`` converts "50%"/"21°"
    to their word form up front, and hassil's ``RangeSlotList`` itself
    natively matches both digit and spelled-out German numbers to the same
    integer (verified empirically, see ``normalize.py``'s own docstring) -
    every existing ``RangeSlotList``-backed slot (percent/temperature/level)
    already produces one canonical int regardless of which surface form was
    spoken. What's been missing is a single typed value+unit pair to carry
    that already-canonical number, instead of three separate ad-hoc ints
    scattered across ``SemanticFrame.parameters`` ("percent"/"temperature"/
    "step_percent" keys) with the unit only implicit from which dict key was
    used.

    Preparatory, like ``SemanticDegree``/this module's other primitives -
    not yet wired into ``frame.py``/``parsers.py`` (replacing the
    ``parameters`` dict keys is a later, separate step so it doesn't risk
    the existing percent/temperature parsing paths; see the Wave 4 results
    for the explicit scoping decision).
    """

    value: float
    unit: NumericUnit

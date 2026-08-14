HomeIntent

Fast, local and deterministic Natural Language Understanding for Home Assistant.

HomeIntent is a lightweight Natural Language Understanding (NLU) engine for Home Assistant Assist.

Its goal is simple:

Understand natural language commands for your smart home quickly, locally and reliably — without requiring an LLM, cloud service or GPU.

HomeIntent is designed specifically for Home Assistant and therefore does not try to understand all of human language. Instead, it focuses on the much smaller and more structured problem of understanding smart-home commands.

⸻

Why HomeIntent?

Large Language Models are powerful, but they are not necessarily the best solution for everyday smart-home commands.

A typical Home Assistant installation may run on:

* Raspberry Pi
* Home Assistant Green
* small x86 systems
* low-power home servers
* other resource-constrained hardware

Running a local LLM on these systems can require significant RAM, CPU resources and sometimes additional hardware.

HomeIntent takes a different approach.

Instead of asking a general-purpose AI to understand everything, HomeIntent uses a deterministic NLU pipeline specifically designed for Home Assistant.

User
 │
 ▼
Natural Language
 │
 ▼
HomeIntent
 │
 ├── Intent Recognition
 ├── Entity Resolution
 ├── Area Resolution
 ├── Quantifiers
 ├── Capability Detection
 ├── Context
 └── Validation
 │
 ▼
Semantic Command
 │
 ▼
Home Assistant

The result is intended to be:

* fast
* local
* deterministic
* predictable
* privacy-friendly
* lightweight
* safe

No cloud connection is required.

No GPU is required.

No LLM is required.

⸻

Current Status

HomeIntent has completed v1 (Deterministic NLU), v2 (Semantic NLU), v3 (Conversational NLU) and v4 (Advanced Natural Language) as defined in the roadmap below. v5 (Natural-Language Automation) has not been started.

Current functionality includes:

* Home Assistant Conversation Agent integration
* German language grammars (hassil-based, 13 separately compiled intent groups)
* deterministic intent matching
* Semantic Frame / Semantic Command pipeline with entity, area and capability resolution
* alias-based entity resolution with deterministic candidate ranking
* domain validation
* percentage values, quantifiers (alle, beide, counted, "nur", "außer"-exclusion)
* ambiguity detection (never guesses on an unresolved match)
* Light, Cover, Fan and Climate control
* query handling, including comparison filters ("heller als 50%"), area-scoped queries ("wie warm ist es im Wohnzimmer"), and state queries over binary_sensor/cover/light/switch ("welche Fenster sind offen", "gibt es offene Fenster", "ist das Fenster im Schlafzimmer geöffnet") - read-only by construction, never calls a service
* conversation context: follow-up commands, clarification questions, pronoun/relative references, cross-sentence query follow-ups
* implicit/relative targets ("oben"/"unten", "im selben Raum")
* temporal expressions (delay, duration, relative/absolute time) - parsed and validated, execution deferred to a later layer
* multi-step commands ("... und ...")
* extensive regression tests (950+ tests, including a generated golden test suite)

The project is actively evolving toward v5 (natural-language automation understanding).

⸻

Example Commands

HomeIntent is designed to understand different natural-language formulations of the same intent.

For example:

Mach das Licht an.
Schalte das Licht ein.
Kannst du bitte das Licht anschalten?

All of these can represent:

TURN_ON

The language can vary while the semantic intent remains the same.

⸻

Multiple Devices

For example:

Mach alle Lichter im Wohnzimmer aus.

The intended semantic structure is:

Intent:     TURN_OFF
Domain:     light
Area:       Wohnzimmer
Quantifier: ALL

⸻

Percentage Values

Examples:

Stell das Licht auf 50 Prozent.
Mach die Rollläden auf 30 %.

The percentage is interpreted as a semantic parameter rather than being tied directly to a specific Home Assistant service.

⸻

Ambiguity

HomeIntent is designed to prefer not executing anything when a command cannot be resolved safely.

For example, if several lights match:

Mach das Licht an.

the engine should not arbitrarily choose one.

Instead, the system can identify the situation as:

AMBIGUOUS_ENTITY

This is an intentional design decision.

A smart-home NLU should prefer asking over controlling the wrong device.

⸻

Architecture

The long-term architecture is based on several separate stages.

Natural Language
       │
       ▼
Normalization
       │
       ▼
Intent Parsing
       │
       ▼
Semantic Frame
       │
       ▼
Entity / Area Resolution
       │
       ▼
Context Resolution
       │
       ▼
Capability Resolution
       │
       ▼
Validation
       │
       ▼
Semantic Command
       │
       ▼
Home Assistant Service Mapping
       │
       ▼
Execution

This separation is important.

The language parser should not directly execute Home Assistant services.

Instead:

Language
   ↓
Meaning
   ↓
Validated Command
   ↓
Home Assistant Service

This makes the system easier to test, extend and secure.

⸻

Semantic Understanding

The long-term goal is to transform natural language into a structured semantic representation.

For example:

Mach bitte die beiden Wohnzimmerlampen etwas heller.

could become:

Intent:
    ADJUST_BRIGHTNESS
Target:
    light
Area:
    Wohnzimmer
Quantifier:
    TWO
Operation:
    INCREASE
Amount:
    SMALL

Only after resolving and validating these values should HomeIntent determine the appropriate Home Assistant service call.

⸻

Entity Resolution

HomeIntent does not rely solely on exact string matching.

The planned resolver considers information such as:

* friendly names
* normalized names
* entity IDs
* aliases
* areas
* domains
* device classes
* capabilities
* conversation context

A future resolver can therefore distinguish between:

Wohnzimmer Deckenlicht
Wohnzimmer Stehlampe
Küchen Deckenlicht

when the user says:

Mach die Deckenlampe im Wohnzimmer an.

The resolver should rank candidates deterministically and detect genuine ambiguity instead of guessing.

⸻

Capability Awareness

Home Assistant entities do not all support the same operations.

For example:

Light A
- on/off
- brightness
- color
Light B
- on/off
- brightness

The command:

Mach Light A blau.

can be valid.

The same command for Light B should result in an unsupported-capability response rather than an invalid service call.

This capability-based architecture allows HomeIntent to reason about what a device can actually do.

⸻

Roadmap

v1 – Deterministic NLU

Completed

The foundation for deterministic natural-language understanding.

Includes:

* hassil
* intent grammars
* entity resolution
* area resolution
* quantifiers
* percentage handling
* domain validation
* Home Assistant service execution
* regression testing

⸻

v2 – Semantic NLU

Completed

Goals:

* Semantic Frames
* Semantic Commands
* improved Entity Resolver
* aliases
* improved Area Resolver
* deterministic candidate ranking
* capability system
* command validation
* service mapping
* query engine
* expanded Light support
* expanded Cover support
* Fan support
* Climate support
* structured responses
* extensive golden tests

The key change:

v1:
Text
 ↓
Intent
 ↓
Service
v2:
Text
 ↓
Semantic Frame
 ↓
Resolution
 ↓
Capabilities
 ↓
Validation
 ↓
Semantic Command
 ↓
Service

⸻

v3 – Conversational NLU

Completed

The engine understands conversations rather than isolated commands.

Goals:

* conversation context
* follow-up commands
* clarification questions
* pending commands
* pronoun resolution
* references to previous entities
* context-aware targets
* multi-turn interactions

Example:

User:
Mach das Wohnzimmerlicht an.
Assistant:
Okay.
User:
Mach es etwas heller.

The second command can refer to the previously selected entity.

⸻

v4 – Advanced Natural Language

Completed

The focus shifted toward more natural German language without introducing an LLM requirement. See docs/architecture-v4.md for implementation details of each sub-section (V4.1-V4.9) and the deliberately deferred items (e.g. "hier", "nebenan", ordinal selection) that would have required guessing without a real data source. A later addition within v4, the Semantic Query Engine (state queries over binary_sensor/cover/light/switch, read-only by construction), is documented separately in docs/architecture-v4-query.md.

Implemented capabilities:

Implicit Targets

Mach oben die Lichter aus.

Relative Locations

Mach die Lampe neben dem Sofa an.

Complex Quantifiers

Mach die drei Lampen an.
Alle außer der Stehlampe aus.

Better Number Understanding

fünfzig Prozent
50 %
auf 21 Grad
Stufe drei

Comparisons

Mindestens 50 Prozent.
Nicht höher als 70 Prozent.

Temporal Expressions

Mach das Licht in fünf Minuten aus.
Schalte die Heizung für eine Stunde ein.

Multi-Step Commands

Mach das Wohnzimmerlicht an und fahr gleichzeitig die Rollläden hoch.

Cross-Sentence References

Wie warm ist es im Wohnzimmer?
Und in der Küche?
Und oben?

Semantic Query Engine (State Queries)

Welche Fenster sind offen?
Gibt es offene Fenster im Keller?
Ist das Fenster im Schlafzimmer geöffnet?
Und im Bad? (cross-sentence follow-up, same as above)

⸻

v5 – Natural-Language Automation

A possible future direction is understanding natural-language automation requests.

For example:

Wenn ich das Haus verlasse, mach alle Lichter aus und fahr die Rollläden runter.

or:

Wenn es draußen dunkel wird, mach das Wohnzimmerlicht auf 30 Prozent.

This would move HomeIntent beyond simple Assist commands toward a natural-language automation layer.

This stage is intentionally separate from the core NLU roadmap.

⸻

Design Principles

Local First

HomeIntent should work without:

* cloud APIs
* external servers
* GPU hardware
* LLMs

⸻

Deterministic First

Given the same:

input
+
Home Assistant state
+
context

the engine should produce the same result.

⸻

Safety First

The engine should never execute an uncertain command merely to produce a successful result.

Ambiguous commands should be:

AMBIGUOUS

not randomly resolved.

⸻

Semantic Separation

Natural language understanding and Home Assistant execution are separate layers.

The parser should produce meaning.

The validator should determine whether that meaning is valid.

The service mapper should translate the validated command into Home Assistant operations.

⸻

Lightweight

HomeIntent is designed with low-resource Home Assistant installations in mind.

The goal is that normal smart-home commands can be processed extremely quickly even on small systems such as a Raspberry Pi.

⸻

LLM Policy

HomeIntent does not require an LLM.

The core project deliberately follows a deterministic approach.

An optional LLM integration may be considered in the future as an external adapter, but it must never bypass:

Entity Resolution
Capability Validation
Parameter Validation
Command Validation

An LLM, if ever used, may help produce a semantic representation.

It must never directly control Home Assistant.

The deterministic core remains the authoritative execution layer.

⸻

Project Philosophy

HomeIntent is based on a simple idea:

Smart-home commands are a much smaller language problem than general human language.

A user asking:

Mach das Wohnzimmerlicht auf 40 Prozent.

does not require a general-purpose AI.

The system needs to reliably understand:

intent
target
location
value

and safely turn that into a Home Assistant command.

That makes a lightweight deterministic NLU a very attractive solution for local smart-home systems.

⸻

Development

The project is being developed incrementally.

The development roadmap prioritizes:

1. preserving existing behavior
2. test coverage
3. semantic separation
4. deterministic resolution
5. capability awareness
6. conversational context
7. advanced natural-language understanding

Each major architectural change should be backed by regression tests.

⸻

Contributing

Contributions are welcome.

When adding new language understanding:

* prefer deterministic rules,
* avoid unnecessary complexity,
* add regression tests,
* do not bypass entity validation,
* do not introduce direct service execution into parser code,
* preserve the local-first architecture.

⸻

License

See the repository license for details.

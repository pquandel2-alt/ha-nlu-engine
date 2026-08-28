#!/usr/bin/env python3
"""Reproduce the read-only Legacy/V7 divergence baseline.

The audit deliberately imports the existing test corpora instead of copying
their sentence matrices.  It constructs plans but never owns a Home Assistant
instance and therefore cannot execute a service call.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))
sys.path.insert(0, str(ROOT / "tests"))

from ha_nlu.engine import NluEngine  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.nlu.understanding import ShadowComparison  # noqa: E402
from test_language_eval_corpus import CASES, EVAL_ENTITIES  # noqa: E402
import test_semantic_domain_matrix as domain_matrix  # noqa: E402
import test_semantic_paraphrase_matrix as light_matrix  # noqa: E402


def _light_cases() -> Iterable[tuple[str, str, list[EntitySnapshot]]]:
    entities = [
        EntitySnapshot(
            f"light.matrix_{index}",
            f"Licht {name}",
            "light",
            "off",
            capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
        )
        for index, name in enumerate(light_matrix._TARGETS)
    ]
    for name, service, particle in product(
        light_matrix._TARGETS,
        light_matrix._SHELLS,
        light_matrix._PARTICLES,
    ):
        for shell in light_matrix._SHELLS[service]:
            sentence = shell.format(name=name, particle=particle).replace("  ", " ")
            yield "light_paraphrases", sentence, entities


def _domain_cases() -> Iterable[tuple[str, str, list[EntitySnapshot]]]:
    for spec in domain_matrix._DOMAINS:
        entities = [
            EntitySnapshot(
                f"{spec.domain}.matrix_{index}",
                f"{spec.noun} {name}",
                spec.domain,
                "off",
                capabilities=spec.capabilities,
                attributes=spec.attributes,
            )
            for index, name in enumerate(domain_matrix._NAMES)
        ]
        for name, particle, operation in product(
            domain_matrix._NAMES,
            domain_matrix._PARTICLES,
            spec.operations,
        ):
            for shell in operation.shells:
                sentence = shell.format(
                    particle=particle,
                    nom=spec.nominative,
                    acc=spec.accusative,
                    target=f"{spec.noun} {name}",
                ).replace("  ", " ")
                yield f"domain_{spec.domain}", sentence, entities


def _eval_cases() -> Iterable[tuple[str, str, list[EntitySnapshot]]]:
    for case in CASES:
        for index, sentence in enumerate(case["turns"]):
            yield f"eval:{case['id']}:turn_{index + 1}", sentence, EVAL_ENTITIES


def _classification(comparison: ShadowComparison) -> str:
    legacy = comparison.authoritative.payload
    v7 = comparison.candidate.payload
    if legacy is None and v7 is None:
        return "both_failed"
    if legacy is None:
        return "v7_only"
    if v7 is None:
        return "legacy_only"
    return "identical" if comparison.equivalent else "divergent"


def _payload_summary(payload: object | None) -> object | None:
    if payload is None:
        return None
    plan = getattr(payload, "plan", None)
    if plan is not None:
        return {
            "kind": "plan",
            "domain": plan.domain,
            "service": plan.service,
            "entity_id": plan.entity_id,
            "data": dict(plan.data),
        }
    commands = getattr(payload, "commands", None)
    if commands is not None:
        return {
            "kind": "command_plan",
            "commands": [_payload_summary(command) for command in commands],
        }
    clarification = getattr(payload, "clarification", None)
    if clarification is not None:
        return {
            "kind": "clarification",
            "intent": clarification.pending_intent,
            "entities": [item.entity_id for item in clarification.candidates],
        }
    frame = getattr(payload, "frame", None)
    command = getattr(payload, "command", None)
    entities = (
        getattr(command, "entities", ())
        if command is not None
        else getattr(payload, "context_entities", ())
    )
    if frame is not None or hasattr(payload, "response_text"):
        return {
            "kind": "non_action",
            "intent": getattr(frame, "intent", None),
            "entities": [getattr(entity, "entity_id", None) for entity in entities],
            "response": getattr(payload, "response_text", None),
        }
    return {"kind": type(payload).__name__, "value": repr(payload)}


def build_report(max_examples: int) -> dict[str, object]:
    engine = NluEngine()
    manifest = json.loads(
        (ROOT / "custom_components" / "ha_nlu" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    totals: Counter[str] = Counter()
    safety: Counter[str] = Counter()
    datasets: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, object]]] = defaultdict(list)
    cases = (*_eval_cases(), *_light_cases(), *_domain_cases())
    for dataset, sentence, entities in cases:
        comparison = engine.compare_understanding_pipelines(sentence, entities)
        for outcome in (comparison.authoritative, comparison.candidate):
            if outcome.speech_act.name == "QUERY" and outcome.actionable:
                safety["query_to_action_leakage"] += 1
            if outcome.kind.name == "UNSAFE":
                safety["unsafe_outcomes"] += 1
                if outcome.actionable:
                    safety["unsafe_action_leakage"] += 1
            if outcome.kind.name == "AMBIGUOUS" and outcome.actionable:
                safety["ambiguous_action_leakage"] += 1
        category = _classification(comparison)
        totals[category] += 1
        datasets[dataset][category] += 1
        if len(examples[category]) < max_examples:
            examples[category].append(
                {
                    "dataset": dataset,
                    "text": sentence,
                    "differences": list(comparison.differences),
                    "legacy": _payload_summary(comparison.authoritative.payload),
                    "v7": _payload_summary(comparison.candidate.payload),
                }
            )
    return {
        "schema_version": 1,
        "project_version": manifest["version"],
        "mode": "read_only_no_service_execution",
        "turns": sum(totals.values()),
        "safety": {
            "query_to_action_leakage": safety["query_to_action_leakage"],
            "unsafe_action_leakage": safety["unsafe_action_leakage"],
            "ambiguous_action_leakage": safety["ambiguous_action_leakage"],
            "unsafe_outcomes_observed": safety["unsafe_outcomes"],
        },
        "categories": {
            key: totals[key]
            for key in (
                "identical",
                "legacy_only",
                "v7_only",
                "divergent",
                "both_failed",
            )
        },
        "datasets": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(datasets.items())
        },
        "examples": {
            name: rows for name, rows in sorted(examples.items()) if rows
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path)
    destination.add_argument("--check", type=Path)
    parser.add_argument("--max-examples", type=int, default=12)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = build_report(max(0, args.max_examples))
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.check is not None:
        expected = args.check.read_text(encoding="utf-8")
        if expected != rendered:
            print(f"Shadow report differs from {args.check}", file=sys.stderr)
            return 1
    if not args.quiet:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

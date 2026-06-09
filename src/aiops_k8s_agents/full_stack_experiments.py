from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FullStackEnvironment:
    name: str
    components: tuple[str, ...]


@dataclass(frozen=True)
class FullStackScenario:
    id: str
    fault: str
    metric: str
    query: str
    threshold: float
    service: str
    chaos_manifest: str


@dataclass(frozen=True)
class FullStackVariation:
    id: str
    variable: str
    description: str


@dataclass(frozen=True)
class FullStackExperimentPlan:
    environment: FullStackEnvironment
    scenarios: tuple[FullStackScenario, ...]
    variations: tuple[FullStackVariation, ...]


def load_full_stack_experiment_plan(path: Path | str) -> FullStackExperimentPlan:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    environment = _environment_from_data(data.get("environment", {}))
    scenarios = tuple(
        _scenario_from_data(item) for item in data.get("scenarios", [])
    )
    variations = tuple(
        _variation_from_data(item) for item in data.get("variations", [])
    )
    _validate_unique("scenario", [scenario.id for scenario in scenarios])
    _validate_unique("variation", [variation.id for variation in variations])
    return FullStackExperimentPlan(
        environment=environment,
        scenarios=scenarios,
        variations=variations,
    )


def plan_to_dict(plan: FullStackExperimentPlan) -> dict[str, Any]:
    return {
        "environment": {
            "name": plan.environment.name,
            "components": list(plan.environment.components),
        },
        "scenarios": [
            {
                "id": scenario.id,
                "fault": scenario.fault,
                "metric": scenario.metric,
                "query": scenario.query,
                "threshold": scenario.threshold,
                "service": scenario.service,
                "chaos_manifest": scenario.chaos_manifest,
            }
            for scenario in plan.scenarios
        ],
        "variations": [
            {
                "id": variation.id,
                "variable": variation.variable,
                "description": variation.description,
            }
            for variation in plan.variations
        ],
    }


def _environment_from_data(data: dict[str, Any]) -> FullStackEnvironment:
    return FullStackEnvironment(
        name=str(data["name"]),
        components=tuple(str(component) for component in data.get("components", [])),
    )


def _scenario_from_data(data: dict[str, Any]) -> FullStackScenario:
    return FullStackScenario(
        id=str(data["id"]),
        fault=str(data["fault"]),
        metric=str(data["metric"]),
        query=str(data["query"]),
        threshold=float(data["threshold"]),
        service=str(data["service"]),
        chaos_manifest=str(data["chaos_manifest"]),
    )


def _variation_from_data(data: dict[str, Any]) -> FullStackVariation:
    return FullStackVariation(
        id=str(data["id"]),
        variable=str(data["variable"]),
        description=str(data["description"]),
    )


def _validate_unique(kind: str, values: list[str]) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate {kind} id: {', '.join(duplicates)}")

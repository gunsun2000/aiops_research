from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from aiops_k8s_agents.models import RecoveryActionKind


DEFAULT_AGENT_NAMES = frozenset(
    {
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    }
)


@dataclass(frozen=True)
class MutualSupervisionPolicy:
    version: str
    max_negotiation_rounds: int
    max_replan_attempts: int
    fallback_action: RecoveryActionKind
    review_matrix: Mapping[str, tuple[str, ...]]

    def reviewers_for(self, target_agent: str) -> tuple[str, ...]:
        return self.review_matrix.get(target_agent, ())


def load_mutual_supervision_policy(
    path: str | Path,
) -> MutualSupervisionPolicy:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    version = str(data.get("version", "")).strip()
    if not version:
        raise ValueError("policy version must not be empty")

    max_rounds = int(data.get("max_negotiation_rounds", 0))
    if max_rounds < 1:
        raise ValueError("max_negotiation_rounds must be at least 1")

    max_replans = int(data.get("max_replan_attempts", -1))
    if max_replans < 0:
        raise ValueError("max_replan_attempts must be at least 0")

    fallback_raw = str(data.get("fallback_action", "")).strip()
    try:
        fallback = RecoveryActionKind(fallback_raw)
    except ValueError as exc:
        raise ValueError(
            f"fallback_action must be a bounded recovery action: {fallback_raw}"
        ) from exc

    matrix_data = data.get("review_matrix")
    if not isinstance(matrix_data, dict):
        raise ValueError("review_matrix must be an object")

    matrix: dict[str, tuple[str, ...]] = {}
    for target, reviewers in matrix_data.items():
        if target not in DEFAULT_AGENT_NAMES:
            raise ValueError(f"unknown review target: {target}")
        if not isinstance(reviewers, list) or not reviewers:
            raise ValueError(f"reviewers for {target} must be a non-empty list")
        normalized_reviewers = tuple(str(reviewer) for reviewer in reviewers)
        unknown = set(normalized_reviewers) - DEFAULT_AGENT_NAMES
        if unknown:
            raise ValueError(
                f"unknown review participant: {', '.join(sorted(unknown))}"
            )
        if target in normalized_reviewers:
            raise ValueError(f"agent cannot peer-review itself: {target}")
        matrix[target] = normalized_reviewers

    missing_targets = DEFAULT_AGENT_NAMES - set(matrix)
    if missing_targets:
        raise ValueError(
            "review_matrix is missing default agents: "
            + ", ".join(sorted(missing_targets))
        )

    return MutualSupervisionPolicy(
        version=version,
        max_negotiation_rounds=max_rounds,
        max_replan_attempts=max_replans,
        fallback_action=fallback,
        review_matrix=MappingProxyType(matrix),
    )

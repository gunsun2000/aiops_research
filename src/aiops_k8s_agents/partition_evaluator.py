from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aiops_k8s_agents.model_partition_agent import ModelPartitionPolicy
from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionExecutionPlan,
)
from aiops_k8s_agents.partition_validator import PartitionValidationResult


@dataclass(frozen=True)
class ObservedPartitionMetrics:
    latency_ms: float
    maximum_memory_pressure: float
    total_transfer_bytes: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ObservedPartitionMetrics:
        return cls(
            latency_ms=float(payload["latency_ms"]),
            maximum_memory_pressure=float(payload["maximum_memory_pressure"]),
            total_transfer_bytes=int(payload["total_transfer_bytes"]),
        )


@dataclass(frozen=True)
class PartitionEvaluation:
    reward: float
    evidence_level: str
    estimated: bool
    label: str
    policy_version: str
    components: dict[str, float]
    metrics: dict[str, float | int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reward": self.reward,
            "evidence_level": self.evidence_level,
            "estimated": self.estimated,
            "label": self.label,
            "policy_version": self.policy_version,
            "components": dict(self.components),
            "metrics": dict(self.metrics),
        }


class PartitionPlanEvaluator:
    def __init__(self, policy: ModelPartitionPolicy) -> None:
        self.policy = policy

    def evaluate(
        self,
        round_plan: FederatedRoundPlan,
        plan: PartitionExecutionPlan,
        validation: PartitionValidationResult,
        *,
        observed: ObservedPartitionMetrics | None = None,
    ) -> PartitionEvaluation:
        selected = plan.selected_candidate
        if observed is not None:
            latency_ms = max(0.0, observed.latency_ms)
            memory_pressure = max(0.0, observed.maximum_memory_pressure)
            transfer_bytes = max(0, observed.total_transfer_bytes)
            evidence_level = "observed"
            estimated = False
            label = "Observed reward (runtime evidence)"
        elif selected is not None:
            latency_ms = selected.estimated_total_latency_ms
            memory_pressure = selected.maximum_memory_pressure
            transfer_bytes = selected.total_transfer_bytes
            evidence_level = "predicted"
            estimated = True
            label = "Estimated reward (predicted evidence)"
        else:
            latency_ms = self.policy.latency_reference_ms
            memory_pressure = 1.0
            transfer_bytes = self.policy.transfer_reference_bytes
            evidence_level = "predicted"
            estimated = True
            label = "Estimated reward (no feasible plan)"

        constraint = 1.0 if validation.valid and plan.valid else -1.0
        latency_limit = round_plan.constraints.max_end_to_end_latency_ms
        if latency_limit is not None:
            latency_efficiency = _clamp(1.0 - latency_ms / latency_limit)
        else:
            latency_efficiency = 1.0 / (
                1.0 + latency_ms / self.policy.latency_reference_ms
            )
        memory_safety = _clamp(1.0 - memory_pressure)
        communication_efficiency = 1.0 / (
            1.0 + transfer_bytes / self.policy.transfer_reference_bytes
        )
        components = {
            "constraint_satisfaction": round(constraint, 6),
            "latency_efficiency": round(latency_efficiency, 6),
            "memory_safety": round(memory_safety, 6),
            "communication_efficiency": round(communication_efficiency, 6),
        }
        reward = (
            0.40 * constraint
            + 0.25 * latency_efficiency
            + 0.20 * memory_safety
            + 0.15 * communication_efficiency
        )
        reward = max(-1.0, min(1.0, reward))
        if not validation.valid or not plan.valid:
            reward = min(0.0, reward)
        return PartitionEvaluation(
            reward=round(reward, 6),
            evidence_level=evidence_level,
            estimated=estimated,
            label=label,
            policy_version=self.policy.version,
            components=components,
            metrics={
                "latency_ms": round(latency_ms, 6),
                "maximum_memory_pressure": round(memory_pressure, 6),
                "total_transfer_bytes": transfer_bytes,
            },
        )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))

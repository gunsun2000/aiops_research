from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping

from aiops_k8s_agents.model_partition_agent import ModelPartitionPolicy
from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionExecutionPlan,
)
from aiops_k8s_agents.partition_strategies import PartitionStrategyRegistry
from aiops_k8s_agents.partition_validator import (
    PartitionValidationResult,
    predicted_inference_throughput_capacity,
    predicted_snapshot_availability_feasibility,
)


@dataclass(frozen=True)
class ObservedPartitionMetrics:
    latency_ms: float
    maximum_memory_pressure: float
    total_transfer_bytes: int
    source: str = ""
    observed_at: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ObservedPartitionMetrics:
        metrics = cls(
            latency_ms=_runtime_float(payload.get("latency_ms"), "latency_ms"),
            maximum_memory_pressure=_runtime_float(
                payload.get("maximum_memory_pressure"), "maximum_memory_pressure"
            ),
            total_transfer_bytes=_runtime_transfer_bytes(
                payload.get("total_transfer_bytes")
            ),
            source=_runtime_text(payload.get("source"), "source"),
            observed_at=_runtime_text(payload.get("observed_at"), "observed_at"),
        )
        if not metrics.is_complete_runtime_evidence():
            raise ValueError("runtime evidence requires nonblank source and observed_at")
        return metrics

    def is_complete_runtime_evidence(self) -> bool:
        _validate_runtime_metrics(self)
        source = _runtime_text(self.source, "source")
        observed_at = _runtime_text(self.observed_at, "observed_at")
        if observed_at:
            _parse_runtime_timestamp(observed_at)
        return bool(source and observed_at)


@dataclass(frozen=True)
class PartitionEvaluation:
    reward: float
    evidence_level: str
    estimated: bool
    label: str
    policy_version: str
    components: dict[str, float]
    metrics: dict[str, float | int | str]
    confidence: float = 0.0
    strategy_id: str = "legacy-partition-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "reward": self.reward,
            "evidence_level": self.evidence_level,
            "estimated": self.estimated,
            "label": self.label,
            "policy_version": self.policy_version,
            "components": dict(self.components),
            "metrics": dict(self.metrics),
            "confidence": self.confidence,
            "strategy_id": self.strategy_id,
        }


class PartitionPlanEvaluator:
    def __init__(
        self,
        policy: ModelPartitionPolicy,
        *,
        common_processor: PartitionCommonProcessor | None = None,
        strategy_registry: PartitionStrategyRegistry | None = None,
    ) -> None:
        self.policy = policy
        self._common_processor = common_processor or PartitionCommonProcessor()
        self._strategy_registry = strategy_registry or PartitionStrategyRegistry.default()

    def evaluate(
        self,
        request: FederatedRoundPlan | PartitionPlanningRequest,
        plan: PartitionExecutionPlan,
        validation: PartitionValidationResult,
        *,
        observed: ObservedPartitionMetrics | None = None,
    ) -> PartitionEvaluation:
        round_plan = self._round_plan(request)
        selected = plan.selected_candidate
        observed_is_runtime = (
            observed.is_complete_runtime_evidence() if observed is not None else False
        )
        if observed_is_runtime and observed is not None:
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
        if plan.plan_type == "training":
            components, reward = self._evaluate_training(
                request, plan, constraint, memory_pressure, transfer_bytes
            )
        else:
            components, reward = self._evaluate_inference(
                request,
                round_plan,
                plan,
                constraint,
                latency_ms,
                memory_pressure,
                transfer_bytes,
            )
        if not validation.valid or not plan.valid:
            reward = min(0.0, reward)
        metrics: dict[str, float | int | str] = {
            "latency_ms": round(latency_ms, 6),
            "maximum_memory_pressure": round(memory_pressure, 6),
            "total_transfer_bytes": transfer_bytes,
        }
        if isinstance(request, PartitionPlanningRequest) and plan.plan_type == "inference":
            self._add_inference_planning_metrics(metrics, request, round_plan, plan)
        return PartitionEvaluation(
            reward=round(max(-1.0, min(1.0, reward)), 6),
            evidence_level=evidence_level,
            estimated=estimated,
            label=label,
            policy_version=self.policy.version,
            components=components,
            metrics=metrics,
            confidence=plan.confidence,
            strategy_id=plan.strategy_id,
        )

    def _evaluate_inference(
        self,
        request: FederatedRoundPlan | PartitionPlanningRequest,
        round_plan: FederatedRoundPlan,
        plan: PartitionExecutionPlan,
        constraint: float,
        latency_ms: float,
        memory_pressure: float,
        transfer_bytes: int,
    ) -> tuple[dict[str, float], float]:
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
        if isinstance(request, PartitionPlanningRequest):
            weights = self._strategy_weights(request)
            reward = (
                weights["latency"] * latency_efficiency
                + weights["memory_pressure"] * memory_safety
                + weights["communication"] * communication_efficiency
            )
        else:
            # Preserve the legacy evaluator formula for FederatedRoundPlan callers.
            reward = (
                0.40 * constraint
                + 0.25 * latency_efficiency
                + 0.20 * memory_safety
                + 0.15 * communication_efficiency
            )
        return components, reward

    def _evaluate_training(
        self,
        request: FederatedRoundPlan | PartitionPlanningRequest,
        plan: PartitionExecutionPlan,
        constraint: float,
        memory_pressure: float,
        transfer_bytes: int,
    ) -> tuple[dict[str, float], float]:
        selected = plan.selected_candidate
        if selected is None:
            step_time_ms = self.policy.latency_reference_ms
            imbalance = 1.0
            resilience = 0.0
        else:
            step_time_ms = selected.estimated_step_time_ms
            imbalance = selected.maximum_load_imbalance
            resilience = 1.0 - selected.predicted_resilience_risk
        step_time_efficiency = 1.0 / (
            1.0 + step_time_ms / self.policy.latency_reference_ms
        )
        load_balance = _clamp(1.0 - imbalance)
        memory_safety = _clamp(1.0 - memory_pressure)
        communication_efficiency = 1.0 / (
            1.0 + transfer_bytes / self.policy.transfer_reference_bytes
        )
        weights = self._strategy_weights(request)
        components = {
            "constraint_satisfaction": round(constraint, 6),
            "step_time_efficiency": round(step_time_efficiency, 6),
            "load_balance": round(load_balance, 6),
            "memory_safety": round(memory_safety, 6),
            "communication_efficiency": round(communication_efficiency, 6),
            "resilience": round(_clamp(resilience), 6),
        }
        reward = (
            weights["step_time"] * step_time_efficiency
            + weights["load_balance"] * load_balance
            + weights["memory_pressure"] * memory_safety
            + weights["communication"] * communication_efficiency
            + weights["resilience"] * _clamp(resilience)
        )
        return components, reward

    def _strategy_weights(
        self,
        request: FederatedRoundPlan | PartitionPlanningRequest,
    ) -> dict[str, float]:
        if isinstance(request, PartitionPlanningRequest):
            normalized = self._common_processor.process(request)
            strategy = self._strategy_registry.resolve(
                normalized.plan_type, normalized.approved_execution_mode.name
            )
            return dict(strategy.build_partition_intent(normalized).objective_weights)
        return {
            "step_time": 0.35,
            "load_balance": 0.20,
            "memory_pressure": 0.20,
            "communication": 0.15,
            "resilience": 0.10,
        }

    @staticmethod
    def _add_inference_planning_metrics(
        metrics: dict[str, float | int | str],
        request: PartitionPlanningRequest,
        round_plan: FederatedRoundPlan,
        plan: PartitionExecutionPlan,
    ) -> None:
        throughput_capacity = predicted_inference_throughput_capacity(request, plan)
        if throughput_capacity is None:
            metrics["throughput_capacity_evidence"] = "unverifiable"
        else:
            metrics["predicted_throughput_capacity_rps"] = round(
                throughput_capacity, 6
            )
            metrics["throughput_capacity_evidence"] = "predicted"
        availability_feasibility = predicted_snapshot_availability_feasibility(
            round_plan, plan
        )
        if availability_feasibility is None:
            metrics["availability_evidence"] = "unverifiable"
        else:
            metrics["predicted_snapshot_availability_feasibility"] = (
                availability_feasibility
            )
            metrics["availability_evidence"] = "predicted_snapshot_feasibility"

    def _round_plan(
        self, request: FederatedRoundPlan | PartitionPlanningRequest
    ) -> FederatedRoundPlan:
        if isinstance(request, FederatedRoundPlan):
            return request
        normalized = self._common_processor.process(request)
        return FederatedRoundPlan(
            job_id=normalized.job_id,
            model_id=normalized.model_id,
            execution_mode=normalized.approved_execution_mode,
            layers=normalized.layers,
            participants=normalized.participants,
            devices=normalized.devices,
            network_links=normalized.network_links,
            constraints=normalized.constraints,
        )


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _runtime_float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"runtime evidence {field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"runtime evidence {field} must be numeric") from exc
    if not isfinite(number) or number < 0.0:
        raise ValueError(f"runtime evidence {field} must be finite and nonnegative")
    return number


def _runtime_transfer_bytes(value: Any) -> int:
    number = _runtime_float(value, "total_transfer_bytes")
    if not number.is_integer():
        raise ValueError("runtime evidence total_transfer_bytes must be an integer")
    return int(number)


def _runtime_text(value: Any, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"runtime evidence {field} must be text")
    return value.strip()


def _validate_runtime_metrics(metrics: ObservedPartitionMetrics) -> None:
    _runtime_float(metrics.latency_ms, "latency_ms")
    _runtime_float(metrics.maximum_memory_pressure, "maximum_memory_pressure")
    _runtime_transfer_bytes(metrics.total_transfer_bytes)


def _parse_runtime_timestamp(value: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("runtime evidence observed_at must be ISO-8601") from exc

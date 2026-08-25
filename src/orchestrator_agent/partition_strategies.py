from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Protocol

from orchestrator_agent.partition_common import NormalizedPartitionRequest
from orchestrator_agent.partition_models import PartitionContractError


@dataclass(frozen=True)
class PartitionIntent:
    strategy_id: str
    strategy_version: str
    allowed_partition_methods: tuple[str, ...]
    allowed_split_boundaries: tuple[int, ...]
    forbidden_split_boundaries: tuple[int, ...]
    graph_requirements: tuple[str, ...]
    memory_rules: tuple[str, ...]
    communication_rules: tuple[str, ...]
    optimization_objectives: tuple[str, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    objective_weights: tuple[tuple[str, float], ...] = ()


class PartitionStrategy(Protocol):
    strategy_id: str
    strategy_version: str

    def build_partition_intent(
        self, request: NormalizedPartitionRequest
    ) -> PartitionIntent: ...

    def catalog_contract(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class InferencePartitionStrategy:
    strategy_id: str
    strategy_version: str
    policy_version: str
    supported_modes: tuple[str, ...]
    objective_weights: tuple[tuple[str, float], ...]
    base_confidence: float
    missing_forecast_penalty: float
    legacy_input_penalty: float

    def catalog_contract(self) -> dict[str, Any]:
        return {
            "objective_weights": dict(self.objective_weights),
            "optimization_objectives": [
                f"predicted_{name}:{weight:g}" for name, weight in self.objective_weights
            ],
            "allowed_split_boundary_rule": "interior_layer_boundaries",
            "forbidden_split_boundaries": ["first_boundary", "last_boundary"],
            "graph_requirements": [
                "forward_only_dag",
                "adjacent_partition_edges_only",
            ],
            "memory_rules": [
                "per_partition_parameter_bytes",
                "per_partition_working_memory_bytes",
                "per_partition_peak_activation_bytes",
            ],
            "communication_rules": [
                "forward_activation_transfer_only",
                "adjacent_partition_transfer_only",
            ],
        }

    def build_partition_intent(
        self, request: NormalizedPartitionRequest
    ) -> PartitionIntent:
        mode = request.approved_execution_mode.name
        if request.plan_type != "inference" or mode not in self.supported_modes:
            raise PartitionContractError(
                "strategy_not_supported",
                f"strategy {self.strategy_id} does not support {request.plan_type}/{mode}",
            )

        layer_count = len(request.layers)
        confidence = self.base_confidence
        warnings: list[str] = []
        if not request.workload_forecast_available:
            confidence -= self.missing_forecast_penalty
            warnings.append("workload_forecast_missing: confidence reduced")
        if request.legacy_input:
            confidence -= self.legacy_input_penalty
            warnings.append("legacy_input: confidence reduced")

        return PartitionIntent(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            allowed_partition_methods=(mode,),
            allowed_split_boundaries=tuple(range(1, layer_count)),
            forbidden_split_boundaries=(0, layer_count),
            graph_requirements=(
                "forward_only_dag",
                "adjacent_partition_edges_only",
            ),
            memory_rules=(
                "per_partition_parameter_bytes",
                "per_partition_working_memory_bytes",
                "per_partition_peak_activation_bytes",
            ),
            communication_rules=(
                "forward_activation_transfer_only",
                "adjacent_partition_transfer_only",
            ),
            optimization_objectives=tuple(
                f"predicted_{name}:{weight:g}" for name, weight in self.objective_weights
            ),
            assumptions=(
                f"approved_execution_mode:{mode}",
                f"approved_model_version:{request.approved_model_version}",
                f"context_snapshot_id:{request.context_snapshot_id}",
                f"context_snapshot_hash:{request.context_snapshot_hash}",
                f"input_signature:{request.input_signature}",
                f"policy_version:{self.policy_version}",
                f"planning_confidence:{max(confidence, 0.0):g}",
            ),
            warnings=tuple(warnings),
            objective_weights=self.objective_weights,
        )


@dataclass(frozen=True)
class TrainingPartitionStrategy:
    strategy_id: str
    strategy_version: str
    policy_version: str
    supported_modes: tuple[str, ...]
    objective_weights: tuple[tuple[str, float], ...]
    forbidden_split_boundaries: tuple[int, ...]
    base_confidence: float
    missing_forecast_penalty: float
    legacy_input_penalty: float

    def catalog_contract(self) -> dict[str, Any]:
        return {
            "objective_weights": dict(self.objective_weights),
            "optimization_objectives": [
                f"predicted_{name}:{weight:g}" for name, weight in self.objective_weights
            ],
            "allowed_split_boundary_rule": "interior_layer_boundaries",
            "forbidden_split_boundaries": [
                "first_boundary",
                *self.forbidden_split_boundaries,
                "last_boundary",
            ],
            "graph_requirements": [
                "phase_distinct_training_dag",
                "forward_backward_gradient_aggregation_edges",
                "adjacent_partition_edges_only",
            ],
            "memory_rules": [
                "per_partition_parameter_bytes",
                "per_partition_working_memory_bytes",
                "per_partition_peak_activation_bytes",
                "checkpoint_boundary_memory",
            ],
            "communication_rules": [
                "forward_activation_transfer",
                "backward_gradient_transfer",
                "aggregation_transfer",
            ],
        }

    def build_partition_intent(
        self, request: NormalizedPartitionRequest
    ) -> PartitionIntent:
        mode = request.approved_execution_mode.name
        if request.plan_type != "training" or mode not in self.supported_modes:
            raise PartitionContractError(
                "strategy_not_supported",
                f"strategy {self.strategy_id} does not support {request.plan_type}/{mode}",
            )

        layer_count = len(request.layers)
        confidence = self.base_confidence
        warnings: list[str] = []
        if not request.workload_forecast_available:
            confidence -= self.missing_forecast_penalty
            warnings.append("workload_forecast_missing: confidence reduced")
        if request.legacy_input:
            confidence -= self.legacy_input_penalty
            warnings.append("legacy_input: confidence reduced")

        forbidden = tuple(
            boundary
            for boundary in self.forbidden_split_boundaries
            if 0 < boundary < layer_count
        )
        return PartitionIntent(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            allowed_partition_methods=(mode,),
            allowed_split_boundaries=tuple(
                boundary
                for boundary in range(1, layer_count)
                if boundary not in forbidden
            ),
            forbidden_split_boundaries=(0, *forbidden, layer_count),
            graph_requirements=(
                "phase_distinct_training_dag",
                "forward_backward_gradient_aggregation_edges",
                "adjacent_partition_edges_only",
            ),
            memory_rules=(
                "per_partition_parameter_bytes",
                "per_partition_working_memory_bytes",
                "per_partition_peak_activation_bytes",
                "checkpoint_boundary_memory",
            ),
            communication_rules=(
                "forward_activation_transfer",
                "backward_gradient_transfer",
                "aggregation_transfer",
            ),
            optimization_objectives=tuple(
                f"predicted_{name}:{weight:g}" for name, weight in self.objective_weights
            ),
            assumptions=(
                f"approved_execution_mode:{mode}",
                f"approved_model_version:{request.approved_model_version}",
                f"context_snapshot_id:{request.context_snapshot_id}",
                f"context_snapshot_hash:{request.context_snapshot_hash}",
                f"input_signature:{request.input_signature}",
                f"policy_version:{self.policy_version}",
                f"planning_confidence:{max(confidence, 0.0):g}",
            ),
            warnings=tuple(warnings),
            objective_weights=self.objective_weights,
        )


@dataclass(frozen=True)
class FederatedFullModelStrategy:
    strategy_id: str
    strategy_version: str
    policy_version: str
    objective_weights: tuple[tuple[str, float], ...]
    base_confidence: float
    missing_forecast_penalty: float

    def catalog_contract(self) -> dict[str, Any]:
        return {
            "objective_weights": dict(self.objective_weights),
            "optimization_objectives": [
                f"predicted_{name}:{weight:g}" for name, weight in self.objective_weights
            ],
            "allowed_split_boundary_rule": "full_model_replica_per_participant",
            "forbidden_split_boundaries": ["all_layer_split_boundaries"],
            "graph_requirements": [
                "full_model_replica_per_participant",
                "participant_to_aggregator_edges",
            ],
            "memory_rules": [
                "full_model_parameter_bytes_per_participant",
                "full_model_working_memory_per_participant",
                "full_model_peak_activation_per_participant",
            ],
            "communication_rules": [
                "remote_model_update_transfer",
                "aggregation_transfer",
            ],
        }

    def build_partition_intent(
        self, request: NormalizedPartitionRequest
    ) -> PartitionIntent:
        mode = request.approved_execution_mode.name
        if request.plan_type != "training" or mode != "federated_learning":
            raise PartitionContractError(
                "strategy_not_supported",
                f"strategy {self.strategy_id} does not support {request.plan_type}/{mode}",
            )
        confidence = self.base_confidence
        warnings: list[str] = []
        if not request.workload_forecast_available:
            confidence -= self.missing_forecast_penalty
            warnings.append("workload_forecast_missing: confidence reduced")
        return PartitionIntent(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            allowed_partition_methods=(mode,),
            allowed_split_boundaries=(),
            forbidden_split_boundaries=tuple(range(0, len(request.layers) + 1)),
            graph_requirements=(
                "full_model_replica_per_participant",
                "participant_to_aggregator_edges",
            ),
            memory_rules=(
                "full_model_parameter_bytes_per_participant",
                "full_model_working_memory_per_participant",
                "full_model_peak_activation_per_participant",
            ),
            communication_rules=(
                "remote_model_update_transfer",
                "aggregation_transfer",
            ),
            optimization_objectives=tuple(
                f"predicted_{name}:{weight:g}" for name, weight in self.objective_weights
            ),
            assumptions=(
                f"approved_execution_mode:{mode}",
                f"approved_model_version:{request.approved_model_version}",
                f"context_snapshot_id:{request.context_snapshot_id}",
                f"context_snapshot_hash:{request.context_snapshot_hash}",
                f"input_signature:{request.input_signature}",
                f"policy_version:{self.policy_version}",
                f"planning_confidence:{max(confidence, 0.0):g}",
            ),
            warnings=tuple(warnings),
            objective_weights=self.objective_weights,
        )


@dataclass(frozen=True)
class PartitionStrategyRegistry:
    entries: tuple[tuple[str, str, PartitionStrategy], ...]

    @classmethod
    def default(cls, policy_path: Path | None = None) -> PartitionStrategyRegistry:
        payload = _load_policy(
            policy_path
            or Path(__file__).resolve().parents[2] / "config" / "model_partition_policy.json"
        )
        policy_version = _text(payload.get("version"), "version")
        strategy_payload = _mapping(
            _mapping(payload.get("strategy_policies"), "strategy_policies").get(
                "inference-partition-v1"
            ),
            "strategy_policies.inference-partition-v1",
        )
        confidence_payload = _mapping(payload.get("confidence"), "confidence")
        supported_modes = _text_tuple(
            strategy_payload.get("supported_modes"),
            "strategy_policies.inference-partition-v1.supported_modes",
        )
        objective_weights = _objective_weights(
            strategy_payload.get("objectives"),
            ("latency", "memory_pressure", "communication"),
            "strategy_policies.inference-partition-v1.objectives",
        )
        strategy = InferencePartitionStrategy(
            strategy_id="inference-partition-v1",
            strategy_version=f"inference-partition-v1:{policy_version}",
            policy_version=policy_version,
            supported_modes=supported_modes,
            objective_weights=objective_weights,
            base_confidence=_fraction(confidence_payload.get("base"), "confidence.base"),
            missing_forecast_penalty=_fraction(
                confidence_payload.get("missing_forecast_penalty"),
                "confidence.missing_forecast_penalty",
            ),
            legacy_input_penalty=_fraction(
                confidence_payload.get("legacy_input_penalty"),
                "confidence.legacy_input_penalty",
            ),
        )
        strategy_policies = _mapping(payload.get("strategy_policies"), "strategy_policies")
        training_payload = strategy_policies.get("training-partition-v1")
        training_strategy = (
            cls._training_strategy(
                _mapping(
                    training_payload,
                    "strategy_policies.training-partition-v1",
                ),
                policy_version,
                confidence_payload,
            )
            if training_payload is not None
            else None
        )
        federated_payload = strategy_policies.get("federated-full-model-v1")
        federated_strategy = (
            cls._federated_strategy(
                _mapping(
                    federated_payload,
                    "strategy_policies.federated-full-model-v1",
                ),
                policy_version,
                confidence_payload,
            )
            if federated_payload is not None
            else None
        )
        entries: list[tuple[str, str, PartitionStrategy]] = [
            ("inference", mode, strategy) for mode in strategy.supported_modes
        ]
        if training_strategy is not None:
            entries.extend(
                ("training", mode, training_strategy)
                for mode in training_strategy.supported_modes
            )
        if federated_strategy is not None:
            entries.append(("training", "federated_learning", federated_strategy))
        return cls(entries=tuple(entries))

    @staticmethod
    def _training_strategy(
        payload: Mapping[str, Any],
        policy_version: str,
        confidence_payload: Mapping[str, Any],
    ) -> TrainingPartitionStrategy:
        return TrainingPartitionStrategy(
            strategy_id="training-partition-v1",
            strategy_version=f"training-partition-v1:{policy_version}",
            policy_version=policy_version,
            supported_modes=_text_tuple(
                payload.get("supported_modes"),
                "strategy_policies.training-partition-v1.supported_modes",
            ),
            objective_weights=_objective_weights(
                payload.get("objectives"),
                ("step_time", "load_balance", "memory_pressure", "communication", "resilience"),
                "strategy_policies.training-partition-v1.objectives",
            ),
            forbidden_split_boundaries=_boundary_tuple(
                payload.get("forbidden_split_boundaries", []),
                "strategy_policies.training-partition-v1.forbidden_split_boundaries",
            ),
            base_confidence=_fraction(confidence_payload.get("base"), "confidence.base"),
            missing_forecast_penalty=_fraction(
                confidence_payload.get("missing_forecast_penalty"),
                "confidence.missing_forecast_penalty",
            ),
            legacy_input_penalty=_fraction(
                confidence_payload.get("legacy_input_penalty"),
                "confidence.legacy_input_penalty",
            ),
        )

    @staticmethod
    def _federated_strategy(
        payload: Mapping[str, Any],
        policy_version: str,
        confidence_payload: Mapping[str, Any],
    ) -> FederatedFullModelStrategy:
        return FederatedFullModelStrategy(
            strategy_id="federated-full-model-v1",
            strategy_version=f"federated-full-model-v1:{policy_version}",
            policy_version=policy_version,
            objective_weights=_objective_weights(
                payload.get("objectives"),
                ("step_time", "load_balance", "memory_pressure", "communication", "resilience"),
                "strategy_policies.federated-full-model-v1.objectives",
            ),
            base_confidence=_fraction(confidence_payload.get("base"), "confidence.base"),
            missing_forecast_penalty=_fraction(
                confidence_payload.get("missing_forecast_penalty"),
                "confidence.missing_forecast_penalty",
            ),
        )

    def resolve(self, plan_type: str, mode: str) -> PartitionStrategy:
        for registered_plan_type, registered_mode, strategy in self.entries:
            if registered_plan_type == plan_type and registered_mode == mode:
                return strategy
        raise PartitionContractError(
            "strategy_not_supported",
            f"no partition strategy supports {plan_type}/{mode}",
        )


def _load_policy(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PartitionContractError(
            "invalid_partition_policy", f"cannot read strategy policy: {path}"
        ) from exc
    return _mapping(payload, "policy")


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PartitionContractError("invalid_partition_policy", f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PartitionContractError("invalid_partition_policy", f"{field} is required")
    return text


def _text_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PartitionContractError("invalid_partition_policy", f"{field} must be an array")
    items = tuple(_text(item, f"{field}[]") for item in value)
    if not items or len(set(items)) != len(items):
        raise PartitionContractError(
            "invalid_partition_policy", f"{field} must contain unique values"
        )
    return items


def _objective_weights(
    value: Any, required: tuple[str, ...], field: str
) -> tuple[tuple[str, float], ...]:
    objectives = _mapping(value, field)
    weights = tuple(
        (name, _fraction(objectives.get(name), f"{field}.{name}")) for name in required
    )
    if abs(sum(weight for _, weight in weights) - 1.0) > 1e-9:
        raise PartitionContractError(
            "invalid_partition_policy", "strategy objective weights must sum to 1.0"
        )
    return weights


def _boundary_tuple(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise PartitionContractError("invalid_partition_policy", f"{field} must be an array")
    boundaries: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise PartitionContractError(
                "invalid_partition_policy", f"{field} must contain positive integers"
            )
        boundaries.append(item)
    if len(boundaries) != len(set(boundaries)):
        raise PartitionContractError(
            "invalid_partition_policy", f"{field} must contain unique values"
        )
    return tuple(sorted(boundaries))


def _fraction(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise PartitionContractError("invalid_partition_policy", f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PartitionContractError(
            "invalid_partition_policy", f"{field} must be numeric"
        ) from exc
    if not isfinite(number) or number < 0.0 or number > 1.0:
        raise PartitionContractError(
            "invalid_partition_policy", f"{field} must be between 0.0 and 1.0"
        )
    return number


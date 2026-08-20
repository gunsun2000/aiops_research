from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from aiops_k8s_agents.partition_common import (
    NormalizedPartitionRequest,
    PartitionCommonProcessor,
)
from aiops_k8s_agents.partition_context import canonical_json
from aiops_k8s_agents.partition_coordination import (
    LegacyFederatedRoundPlanAdapter,
    PartitionPlanningRequest,
)
from aiops_k8s_agents.partition_models import (
    ExecutionGraphEdge,
    ExecutionGraphNode,
    FederatedRoundPlan,
    LogicalPartition,
    PartitionCandidate,
    PartitionContractError,
    PartitionExecutionPlan,
    PartitionFailure,
    ResourceDevice,
)
from aiops_k8s_agents.partition_strategies import (
    PartitionIntent,
    PartitionStrategyRegistry,
)


@dataclass(frozen=True)
class ModelPartitionPolicy:
    version: str
    latency_weight: float
    memory_pressure_weight: float
    communication_weight: float
    latency_reference_ms: float
    transfer_reference_bytes: int
    max_replan_attempts: int

    @classmethod
    def from_path(cls, path: str | Path) -> ModelPartitionPolicy:
        with Path(path).open(encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    @classmethod
    def from_dict(cls, payload: dict) -> ModelPartitionPolicy:
        weights = payload.get("weights", {})
        normalization = payload.get("normalization", {})
        policy = cls(
            version=str(payload.get("version") or "").strip(),
            latency_weight=float(weights.get("latency", -1)),
            memory_pressure_weight=float(weights.get("memory_pressure", -1)),
            communication_weight=float(weights.get("communication", -1)),
            latency_reference_ms=float(
                normalization.get("latency_reference_ms", 0)
            ),
            transfer_reference_bytes=int(
                normalization.get("transfer_reference_bytes", 0)
            ),
            max_replan_attempts=int(payload.get("max_replan_attempts", 0)),
        )
        if not policy.version:
            raise PartitionContractError("invalid_partition_policy", "version is required")
        weight_values = (
            policy.latency_weight,
            policy.memory_pressure_weight,
            policy.communication_weight,
        )
        if any(weight < 0 for weight in weight_values) or abs(sum(weight_values) - 1.0) > 1e-9:
            raise PartitionContractError(
                "invalid_partition_policy", "score weights must be non-negative and sum to 1.0"
            )
        if policy.latency_reference_ms <= 0 or policy.transfer_reference_bytes <= 0:
            raise PartitionContractError(
                "invalid_partition_policy", "normalization references must be positive"
            )
        if policy.max_replan_attempts < 1:
            raise PartitionContractError(
                "invalid_partition_policy", "max_replan_attempts must be at least 1"
            )
        return policy


class ModelPartitionOrchestrationAgent:
    def __init__(
        self,
        policy: ModelPartitionPolicy,
        *,
        plan_id_factory: Callable[[], str] | None = None,
        common_processor: PartitionCommonProcessor | None = None,
        strategy_registry: PartitionStrategyRegistry | None = None,
        legacy_adapter: LegacyFederatedRoundPlanAdapter | None = None,
    ) -> None:
        self.policy = policy
        self._plan_id_factory = plan_id_factory or (
            lambda: f"partition-plan-{uuid4().hex}"
        )
        self._common_processor = common_processor or PartitionCommonProcessor()
        self._strategy_registry = strategy_registry or PartitionStrategyRegistry.default()
        self._legacy_adapter = legacy_adapter or LegacyFederatedRoundPlanAdapter()

    def plan(self, round_plan: FederatedRoundPlan) -> PartitionExecutionPlan:
        return self.plan_request(self._legacy_adapter.adapt(round_plan))

    def plan_request(
        self, request: PartitionPlanningRequest
    ) -> PartitionExecutionPlan:
        normalized = self._common_processor.process(request)
        strategy = self._strategy_registry.resolve(
            normalized.plan_type, normalized.approved_execution_mode.name
        )
        intent = strategy.build_partition_intent(normalized)
        plan = self._plan(
            self._round_plan_from_normalized(normalized),
            partition_intent=(intent if normalized.plan_type == "training" else None),
        )
        return self._with_v2_metadata(plan, normalized, intent)

    def replan(
        self,
        round_plan: FederatedRoundPlan,
        previous_plan: PartitionExecutionPlan,
        failure: PartitionFailure,
        *,
        attempt: int,
    ) -> PartitionExecutionPlan:
        if attempt > self.policy.max_replan_attempts:
            return self._safe_failure(round_plan, ("replan_attempts_exhausted",))
        if previous_plan.selected_candidate is None:
            return self._safe_failure(round_plan, ("previous_plan_has_no_candidate",))

        excluded_devices: set[str] = set()
        excluded_links: set[tuple[str, str]] = set()
        excluded_splits: set[tuple[int, ...]] = set()
        memory_limits: dict[str, int] = {}

        if failure.signal == "device_unavailable":
            excluded_devices.add(failure.device_id)
            remaining = [
                participant
                for participant in round_plan.participants
                if participant not in excluded_devices
            ]
            if len(remaining) < 2:
                return self._safe_failure(
                    round_plan, ("insufficient_participants_after_failure",)
                )
        elif failure.signal == "memory_exceeded":
            previous_partition = next(
                (
                    partition
                    for partition in previous_plan.selected_candidate.partitions
                    if partition.device_id == failure.device_id
                ),
                None,
            )
            if previous_partition is None:
                return self._safe_failure(
                    round_plan, ("failed_device_not_in_previous_plan",)
                )
            memory_limits[failure.device_id] = previous_partition.memory_demand_bytes - 1
        elif failure.signal == "latency_slo_violation":
            excluded_splits.add(previous_plan.selected_candidate.split_points)
        elif failure.signal == "transfer_failure":
            excluded_links.add((failure.source_device, failure.target_device))

        return self._plan(
            round_plan,
            excluded_devices=excluded_devices,
            excluded_links=excluded_links,
            excluded_splits=excluded_splits,
            memory_limits=memory_limits,
        )

    def _plan(
        self,
        round_plan: FederatedRoundPlan,
        *,
        excluded_devices: set[str] | None = None,
        excluded_links: set[tuple[str, str]] | None = None,
        excluded_splits: set[tuple[int, ...]] | None = None,
        memory_limits: dict[str, int] | None = None,
        partition_intent: PartitionIntent | None = None,
    ) -> PartitionExecutionPlan:
        excluded_devices = excluded_devices or set()
        excluded_links = excluded_links or set()
        excluded_splits = excluded_splits or set()
        memory_limits = memory_limits or {}
        participants = tuple(
            participant
            for participant in round_plan.participants
            if participant not in excluded_devices
        )
        if len(participants) < 2 or len(round_plan.layers) < len(participants):
            return self._safe_failure(
                round_plan, ("insufficient_participants_after_failure",)
            )

        split_count = len(participants) - 1
        split_options = combinations(range(1, len(round_plan.layers)), split_count)
        candidate_splits = tuple(
            split_points
            for split_points in split_options
            if split_points not in excluded_splits
            and (
                partition_intent is None
                or not any(
                    boundary in partition_intent.forbidden_split_boundaries
                    for boundary in split_points
                )
            )
        )
        candidates = tuple(
            self._build_candidate(
                round_plan,
                participants,
                split_points,
                excluded_links=excluded_links,
                memory_limits=memory_limits,
                partition_intent=partition_intent,
            )
            for split_points in candidate_splits
        )
        ordered = tuple(
            sorted(candidates, key=lambda item: (not item.valid, item.score, item.split_points))
        )
        selected = next((candidate for candidate in ordered if candidate.valid), None)
        if selected is None:
            return self._safe_failure(
                round_plan,
                ("no_feasible_partition",),
                alternative_candidates=ordered,
            )
        alternatives = tuple(candidate for candidate in ordered if candidate != selected)
        return PartitionExecutionPlan(
            plan_id=self._plan_id_factory(),
            job_id=round_plan.job_id,
            model_id=round_plan.model_id,
            approved_execution_mode=round_plan.execution_mode.name,
            policy_version=self.policy.version,
            selected_candidate=selected,
            alternative_candidates=alternatives,
            rationale=(
                "Selected the feasible candidate with the lowest versioned "
                "latency, memory-pressure, and communication score."
            ),
            valid=True,
            human_review_required=False,
            errors=(),
        )

    @staticmethod
    def _round_plan_from_normalized(
        request: NormalizedPartitionRequest,
    ) -> FederatedRoundPlan:
        return FederatedRoundPlan(
            job_id=request.job_id,
            model_id=request.model_id,
            execution_mode=request.approved_execution_mode,
            layers=request.layers,
            participants=request.participants,
            devices=request.devices,
            network_links=request.network_links,
            constraints=request.constraints,
        )

    def _with_v2_metadata(
        self,
        plan: PartitionExecutionPlan,
        request: NormalizedPartitionRequest,
        intent: PartitionIntent,
    ) -> PartitionExecutionPlan:
        signature_payload = {
            "input_signature": request.input_signature,
            "strategy_id": intent.strategy_id,
            "strategy_version": intent.strategy_version,
            "policy_version": self.policy.version,
            "selected_candidate": (
                None
                if plan.selected_candidate is None
                else plan.selected_candidate.to_dict()
            ),
        }
        return replace(
            plan,
            plan_version=1,
            parent_plan_id=None,
            plan_type=request.plan_type,
            approved_model_version=request.approved_model_version,
            strategy_id=intent.strategy_id,
            strategy_version=intent.strategy_version,
            input_snapshot_id=request.context_snapshot_id,
            input_snapshot_hash=request.context_snapshot_hash,
            assumptions=intent.assumptions,
            warnings=intent.warnings,
            confidence=self._intent_confidence(intent),
            deterministic_signature=hashlib.sha256(
                canonical_json(signature_payload).encode("utf-8")
            ).hexdigest(),
            handoff_status="not_ready",
        )

    @staticmethod
    def _intent_confidence(intent: PartitionIntent) -> float:
        prefix = "planning_confidence:"
        for assumption in intent.assumptions:
            if assumption.startswith(prefix):
                confidence = float(assumption.removeprefix(prefix))
                if 0.0 <= confidence <= 1.0:
                    return confidence
        raise PartitionContractError(
            "invalid_partition_intent", "strategy intent must include valid confidence"
        )

    def _build_candidate(
        self,
        round_plan: FederatedRoundPlan,
        participants: tuple[str, ...],
        split_points: tuple[int, ...],
        *,
        excluded_links: set[tuple[str, str]],
        memory_limits: dict[str, int],
        partition_intent: PartitionIntent | None = None,
    ) -> PartitionCandidate:
        devices = {device.device_id: device for device in round_plan.devices}
        links = {
            (link.source_device, link.target_device): link
            for link in round_plan.network_links
        }
        boundaries = (0, *split_points, len(round_plan.layers))
        partitions: list[LogicalPartition] = []
        partition_compute_ms: list[float] = []
        compute_ms = 0.0
        memory_pressures: list[float] = []
        rejection_reasons: list[str] = []

        for index, device_id in enumerate(participants):
            layers = round_plan.layers[boundaries[index] : boundaries[index + 1]]
            device = devices[device_id]
            memory_demand = (
                sum(layer.parameter_bytes for layer in layers)
                + sum(layer.working_memory_bytes for layer in layers)
                + max(layer.activation_bytes for layer in layers)
            )
            partition = LogicalPartition(
                partition_id=f"partition-{index + 1}",
                device_id=device_id,
                layer_names=tuple(layer.name for layer in layers),
                compute_units=sum(layer.compute_units for layer in layers),
                memory_demand_bytes=memory_demand,
            )
            partitions.append(partition)
            partition_compute = (
                partition.compute_units / device.compute_units_per_second * 1000.0
            )
            compute_ms += partition_compute
            partition_compute_ms.append(partition_compute)
            pressure = memory_demand / max(1, device.memory_available_bytes)
            memory_pressures.append(pressure)
            allowed_memory = int(
                device.memory_available_bytes
                * (1.0 - round_plan.constraints.minimum_memory_headroom_ratio)
            )
            if memory_demand > allowed_memory:
                rejection_reasons.append(f"memory_capacity_exceeded:{device_id}")
            if device_id in memory_limits and memory_demand > memory_limits[device_id]:
                rejection_reasons.append(f"memory_replan_not_improved:{device_id}")

        graph_nodes = tuple(
            ExecutionGraphNode(partition.partition_id, partition.device_id)
            for partition in partitions
        )
        graph_edges: list[ExecutionGraphEdge] = []
        transfer_ms = 0.0
        transfer_bytes = 0
        for index, (source, target) in enumerate(zip(participants, participants[1:])):
            pair = (source, target)
            if pair in excluded_links:
                rejection_reasons.append(f"failed_network_link:{source}->{target}")
                continue
            link = links.get(pair)
            if link is None:
                rejection_reasons.append(f"missing_network_link:{source}->{target}")
                continue
            boundary_layer = round_plan.layers[split_points[index] - 1]
            edge_bytes = boundary_layer.activation_bytes
            edge_ms = link.latency_ms + edge_bytes / link.bandwidth_bytes_per_second * 1000.0
            transfer_bytes += edge_bytes
            transfer_ms += edge_ms
            graph_edges.append(
                ExecutionGraphEdge(
                    source_partition=partitions[index].partition_id,
                    target_partition=partitions[index + 1].partition_id,
                    transfer_bytes=edge_bytes,
                    estimated_transfer_ms=round(edge_ms, 6),
                )
            )

        estimated_step_time_ms = 0.0
        gradient_transfer_bytes = 0
        maximum_load_imbalance = 0.0
        predicted_resilience_risk = 0.0
        if partition_intent is not None:
            (
                graph_nodes,
                graph_edges,
                transfer_ms,
                transfer_bytes,
                estimated_step_time_ms,
                gradient_transfer_bytes,
                maximum_load_imbalance,
            ) = self._build_training_graph(
                partitions=tuple(partitions),
                forward_edges=tuple(graph_edges),
                partition_compute_ms=tuple(partition_compute_ms),
                forward_transfer_ms=transfer_ms,
                forward_transfer_bytes=transfer_bytes,
            )
            predicted_resilience_risk = self._predicted_resilience_risk(
                tuple(partition_compute_ms), len(participants)
            )

        total_latency = (
            estimated_step_time_ms
            if partition_intent is not None
            else compute_ms + transfer_ms
        )
        if (
            round_plan.constraints.max_transfer_bytes is not None
            and transfer_bytes > round_plan.constraints.max_transfer_bytes
        ):
            rejection_reasons.append("max_transfer_bytes_exceeded")
        if (
            round_plan.constraints.max_end_to_end_latency_ms is not None
            and total_latency > round_plan.constraints.max_end_to_end_latency_ms
        ):
            rejection_reasons.append("latency_slo_exceeded")
        maximum_pressure = max(memory_pressures, default=0.0)
        score = (
            self._score_training(
                estimated_step_time_ms,
                maximum_load_imbalance,
                maximum_pressure,
                transfer_bytes,
                predicted_resilience_risk,
                partition_intent,
            )
            if partition_intent is not None
            else self._score(total_latency, maximum_pressure, transfer_bytes)
        )
        return PartitionCandidate(
            split_points=split_points,
            partitions=tuple(partitions),
            graph_nodes=graph_nodes,
            graph_edges=tuple(graph_edges),
            estimated_compute_ms=round(compute_ms, 6),
            estimated_transfer_ms=round(transfer_ms, 6),
            estimated_total_latency_ms=round(total_latency, 6),
            total_transfer_bytes=transfer_bytes,
            maximum_memory_pressure=round(maximum_pressure, 6),
            valid=not rejection_reasons,
            rejection_reasons=tuple(rejection_reasons),
            score=score,
            estimated_step_time_ms=round(estimated_step_time_ms, 6),
            gradient_transfer_bytes=gradient_transfer_bytes,
            maximum_load_imbalance=round(maximum_load_imbalance, 6),
            predicted_resilience_risk=round(predicted_resilience_risk, 6),
        )

    @staticmethod
    def _build_training_graph(
        *,
        partitions: tuple[LogicalPartition, ...],
        forward_edges: tuple[ExecutionGraphEdge, ...],
        partition_compute_ms: tuple[float, ...],
        forward_transfer_ms: float,
        forward_transfer_bytes: int,
    ) -> tuple[
        tuple[ExecutionGraphNode, ...],
        tuple[ExecutionGraphEdge, ...],
        float,
        int,
        float,
        int,
        float,
    ]:
        forward_nodes = tuple(
            ExecutionGraphNode(f"{partition.partition_id}:forward", partition.device_id)
            for partition in partitions
        )
        backward_nodes = tuple(
            ExecutionGraphNode(f"{partition.partition_id}:backward", partition.device_id)
            for partition in reversed(partitions)
        )
        aggregation_node = ExecutionGraphNode("aggregation", partitions[0].device_id)
        edges: list[ExecutionGraphEdge] = [
            ExecutionGraphEdge(
                source_partition=f"{edge.source_partition}:forward",
                target_partition=f"{edge.target_partition}:forward",
                transfer_bytes=edge.transfer_bytes,
                estimated_transfer_ms=edge.estimated_transfer_ms,
                edge_type="forward",
            )
            for edge in forward_edges
        ]
        last_partition = partitions[-1]
        gradient_bytes = forward_transfer_bytes
        edges.append(
            ExecutionGraphEdge(
                source_partition=f"{last_partition.partition_id}:forward",
                target_partition=f"{last_partition.partition_id}:backward",
                transfer_bytes=gradient_bytes,
                estimated_transfer_ms=0.0,
                edge_type="gradient",
            )
        )
        for edge in reversed(forward_edges):
            edges.append(
                ExecutionGraphEdge(
                    source_partition=f"{edge.target_partition}:backward",
                    target_partition=f"{edge.source_partition}:backward",
                    transfer_bytes=edge.transfer_bytes,
                    estimated_transfer_ms=edge.estimated_transfer_ms,
                    edge_type="backward",
                )
            )
        aggregation_bytes = gradient_bytes
        first_partition = partitions[0]
        edges.append(
            ExecutionGraphEdge(
                source_partition=f"{first_partition.partition_id}:backward",
                target_partition="aggregation",
                transfer_bytes=aggregation_bytes,
                estimated_transfer_ms=0.0,
                edge_type="aggregation",
            )
        )
        maximum_compute_ms = max(partition_compute_ms, default=0.0)
        minimum_compute_ms = min(partition_compute_ms, default=0.0)
        maximum_load_imbalance = (
            0.0
            if maximum_compute_ms == 0.0
            else (maximum_compute_ms - minimum_compute_ms) / maximum_compute_ms
        )
        transfer_ms = forward_transfer_ms * 2.0
        total_transfer_bytes = forward_transfer_bytes * 2 + aggregation_bytes
        estimated_step_time_ms = sum(partition_compute_ms) * 2.0 + transfer_ms
        return (
            (*forward_nodes, *backward_nodes, aggregation_node),
            tuple(edges),
            transfer_ms,
            total_transfer_bytes,
            estimated_step_time_ms,
            gradient_bytes,
            maximum_load_imbalance,
        )

    def _score(
        self,
        total_latency_ms: float,
        maximum_memory_pressure: float,
        total_transfer_bytes: int,
    ) -> float:
        latency = min(total_latency_ms / self.policy.latency_reference_ms, 1.0)
        memory = min(maximum_memory_pressure, 1.0)
        communication = min(
            total_transfer_bytes / self.policy.transfer_reference_bytes, 1.0
        )
        return round(
            self.policy.latency_weight * latency
            + self.policy.memory_pressure_weight * memory
            + self.policy.communication_weight * communication,
            6,
        )

    def _score_training(
        self,
        estimated_step_time_ms: float,
        maximum_load_imbalance: float,
        maximum_memory_pressure: float,
        total_transfer_bytes: int,
        predicted_resilience_risk: float,
        intent: PartitionIntent,
    ) -> float:
        weights = dict(intent.objective_weights)
        step_time = min(
            estimated_step_time_ms / self.policy.latency_reference_ms, 1.0
        )
        communication = min(
            total_transfer_bytes / self.policy.transfer_reference_bytes, 1.0
        )
        return round(
            weights["step_time"] * step_time
            + weights["load_balance"] * maximum_load_imbalance
            + weights["memory_pressure"] * min(maximum_memory_pressure, 1.0)
            + weights["communication"] * communication
            + weights["resilience"] * predicted_resilience_risk,
            6,
        )

    @staticmethod
    def _predicted_resilience_risk(
        partition_compute_ms: tuple[float, ...],
        eligible_participant_count: int,
    ) -> float:
        """Return a bounded planning-only concentration risk; lower is better.

        This is not an observed runtime resilience measurement. It combines the
        largest partition's compute share with the fraction of eligible devices
        left unused by the partition placement.
        """
        if not partition_compute_ms or eligible_participant_count <= 0:
            return 0.0
        total_compute = sum(partition_compute_ms)
        workload_concentration = (
            0.0 if total_compute <= 0.0 else max(partition_compute_ms) / total_compute
        )
        device_concentration = 1.0 - min(
            len(partition_compute_ms), eligible_participant_count
        ) / eligible_participant_count
        return min(max(max(workload_concentration, device_concentration), 0.0), 1.0)

    def _safe_failure(
        self,
        round_plan: FederatedRoundPlan,
        errors: tuple[str, ...],
        *,
        alternative_candidates: Iterable[PartitionCandidate] = (),
    ) -> PartitionExecutionPlan:
        return PartitionExecutionPlan.safe_failure(
            plan_id=self._plan_id_factory(),
            job_id=round_plan.job_id,
            model_id=round_plan.model_id,
            approved_execution_mode=round_plan.execution_mode.name,
            policy_version=self.policy.version,
            errors=errors,
            alternative_candidates=tuple(alternative_candidates),
        )

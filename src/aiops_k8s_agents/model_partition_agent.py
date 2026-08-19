from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

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
    ) -> None:
        self.policy = policy
        self._plan_id_factory = plan_id_factory or (
            lambda: f"partition-plan-{uuid4().hex}"
        )

    def plan(self, round_plan: FederatedRoundPlan) -> PartitionExecutionPlan:
        return self._plan(round_plan)

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
        candidates = tuple(
            self._build_candidate(
                round_plan,
                participants,
                split_points,
                excluded_links=excluded_links,
                memory_limits=memory_limits,
            )
            for split_points in split_options
            if split_points not in excluded_splits
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

    def _build_candidate(
        self,
        round_plan: FederatedRoundPlan,
        participants: tuple[str, ...],
        split_points: tuple[int, ...],
        *,
        excluded_links: set[tuple[str, str]],
        memory_limits: dict[str, int],
    ) -> PartitionCandidate:
        devices = {device.device_id: device for device in round_plan.devices}
        links = {
            (link.source_device, link.target_device): link
            for link in round_plan.network_links
        }
        boundaries = (0, *split_points, len(round_plan.layers))
        partitions: list[LogicalPartition] = []
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
            compute_ms += (
                partition.compute_units / device.compute_units_per_second * 1000.0
            )
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

        total_latency = compute_ms + transfer_ms
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
        score = self._score(total_latency, maximum_pressure, transfer_bytes)
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

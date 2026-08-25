from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import isfinite
from typing import Any

from orchestrator_agent.partition_common import PartitionCommonProcessor
from orchestrator_agent.partition_context import canonical_json
from orchestrator_agent.partition_coordination import PartitionPlanningRequest
from orchestrator_agent.partition_models import (
    FederatedRoundPlan,
    PartitionContractError,
    PartitionExecutionPlan,
)
from orchestrator_agent.partition_strategies import PartitionStrategyRegistry


INFERENCE_FORWARD_EDGE_TYPES = {"forward", "pipeline", "cache_transfer"}


def predicted_inference_throughput_capacity(
    request: PartitionPlanningRequest,
    plan: PartitionExecutionPlan,
) -> float | None:
    """Return a planning-time capacity estimate, never runtime throughput."""
    selected = plan.selected_candidate
    concurrency_policy = getattr(request.plan, "concurrency_policy", None)
    if selected is None or not isinstance(concurrency_policy, dict):
        return None
    max_requests = concurrency_policy.get("max_requests")
    if isinstance(max_requests, bool) or not isinstance(max_requests, int):
        return None
    latency_ms = selected.estimated_total_latency_ms
    if (
        max_requests <= 0
        or not isinstance(latency_ms, (int, float))
        or isinstance(latency_ms, bool)
        or not isfinite(latency_ms)
        or latency_ms <= 0.0
    ):
        return None
    return max_requests * 1_000.0 / latency_ms


def predicted_snapshot_availability_feasibility(
    round_plan: FederatedRoundPlan,
    plan: PartitionExecutionPlan,
) -> float | None:
    """Return snapshot topology feasibility, not an observed reliability claim."""
    selected = plan.selected_candidate
    if selected is None:
        return None
    devices = {device.device_id for device in round_plan.devices}
    participants = set(round_plan.participants)
    if any(
        partition.device_id not in devices or partition.device_id not in participants
        for partition in selected.partitions
    ):
        return 0.0
    expected_nodes = {
        (partition.partition_id, partition.device_id)
        for partition in selected.partitions
    }
    actual_nodes = {
        (node.partition_id, node.device_id) for node in selected.graph_nodes
    }
    if actual_nodes != expected_nodes or not _has_inference_forward_chain(selected):
        return 0.0
    link_pairs = {
        (link.source_device, link.target_device) for link in round_plan.network_links
    }
    for source, target in zip(selected.partitions, selected.partitions[1:]):
        if source.device_id != target.device_id and (
            source.device_id,
            target.device_id,
        ) not in link_pairs:
            return 0.0
    return 1.0


def _has_inference_forward_chain(selected: Any) -> bool:
    return all(
        any(
            edge.source_partition == source.partition_id
            and edge.target_partition == target.partition_id
            and edge.edge_type in INFERENCE_FORWARD_EDGE_TYPES
            for edge in selected.graph_edges
        )
        for source, target in zip(selected.partitions, selected.partitions[1:])
    )


@dataclass(frozen=True)
class PartitionValidationResult:
    valid: bool
    errors: tuple[str, ...]
    checked_rules: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "checked_rules": list(self.checked_rules),
        }


class PartitionPlanValidator:
    TRAINING_GRAPH_MODES = {
        "federated_learning",
        "pipeline_parallel",
        "split_learning",
        "hybrid_partition",
    }
    CHECKED_RULES = (
        "plan_identity",
        "approved_mode_provenance",
        "layer_coverage",
        "partition_devices",
        "memory_capacity",
        "execution_graph_nodes",
        "execution_graph_dag",
        "network_links",
        "job_constraints",
    )
    V2_CHECKED_RULES = (
        *CHECKED_RULES,
        "coordination_approval_provenance",
        "v2_plan_identity",
        "strategy_identity",
        "input_snapshot",
        "deterministic_signature",
        "strategy_graph_contract",
    )

    def __init__(
        self,
        *,
        common_processor: PartitionCommonProcessor | None = None,
        strategy_registry: PartitionStrategyRegistry | None = None,
    ) -> None:
        self._common_processor = common_processor or PartitionCommonProcessor()
        self._strategy_registry = strategy_registry or PartitionStrategyRegistry.default()

    def validate(
        self,
        request: FederatedRoundPlan | PartitionPlanningRequest,
        plan: PartitionExecutionPlan,
    ) -> PartitionValidationResult:
        if isinstance(request, PartitionPlanningRequest):
            return self._validate_v2(request, plan)
        return self._validate_legacy(request, plan)

    def _validate_legacy(
        self,
        round_plan: FederatedRoundPlan,
        plan: PartitionExecutionPlan,
    ) -> PartitionValidationResult:
        errors: list[str] = []
        if plan.job_id != round_plan.job_id:
            errors.append("job_id_mismatch")
        if plan.model_id != round_plan.model_id:
            errors.append("model_id_mismatch")
        if plan.approved_execution_mode != round_plan.execution_mode.name:
            errors.append("approved_execution_mode_mismatch")
        if (
            not round_plan.execution_mode.approved
            or not round_plan.execution_mode.approved_by
            or not round_plan.execution_mode.approval_ref
        ):
            errors.append("approved_mode_provenance_missing")
        selected = plan.selected_candidate
        if selected is None:
            errors.append("selected_candidate_required")
            return self._result(errors)
        if not plan.valid or not selected.valid:
            errors.append("selected_plan_not_valid")

        expected_layer_names = tuple(layer.name for layer in round_plan.layers)
        actual_layer_names = tuple(
            layer_name
            for partition in selected.partitions
            for layer_name in partition.layer_names
        )
        is_federated_learning = (
            plan.plan_type == "training"
            and plan.approved_execution_mode == "federated_learning"
        )
        full_model_replicas_valid = (
            is_federated_learning
            and len(selected.partitions) == len(round_plan.participants)
            and all(
                partition.layer_names == expected_layer_names
                for partition in selected.partitions
            )
        )
        if not full_model_replicas_valid and actual_layer_names != expected_layer_names:
            errors.append("layer_coverage_mismatch")

        layers = {layer.name: layer for layer in round_plan.layers}
        devices = {device.device_id: device for device in round_plan.devices}
        participants = set(round_plan.participants)
        partitions_by_id = {
            partition.partition_id: partition for partition in selected.partitions
        }
        if len(partitions_by_id) != len(selected.partitions):
            errors.append("duplicate_partition_id")
        for partition in selected.partitions:
            if not partition.layer_names:
                errors.append(f"empty_partition:{partition.partition_id}")
            if partition.device_id not in participants or partition.device_id not in devices:
                errors.append(f"unknown_partition_device:{partition.device_id}")
                continue
            if any(name not in layers for name in partition.layer_names):
                errors.append(f"unknown_partition_layer:{partition.partition_id}")
                continue
            assigned_layers = tuple(layers[name] for name in partition.layer_names)
            expected_memory = (
                sum(layer.parameter_bytes for layer in assigned_layers)
                + sum(layer.working_memory_bytes for layer in assigned_layers)
                + max(layer.activation_bytes for layer in assigned_layers)
            )
            if partition.memory_demand_bytes != expected_memory:
                errors.append(f"memory_demand_mismatch:{partition.partition_id}")
            allowed_memory = int(
                devices[partition.device_id].memory_available_bytes
                * (1.0 - round_plan.constraints.minimum_memory_headroom_ratio)
            )
            if expected_memory > allowed_memory:
                errors.append(f"memory_capacity_exceeded:{partition.device_id}")

        is_training_plan = plan.plan_type == "training"
        node_partitions = self._graph_node_partitions(
            selected.partitions,
            is_training_plan,
            plan.approved_execution_mode,
        )
        expected_nodes = {
            (node_id, partition.device_id)
            for node_id, partition in node_partitions.items()
        }
        actual_nodes = {
            (node.partition_id, node.device_id) for node in selected.graph_nodes
        }
        if actual_nodes != expected_nodes:
            errors.append("graph_node_partition_mismatch")

        node_ids = {node.partition_id for node in selected.graph_nodes}
        adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        link_pairs = {
            (link.source_device, link.target_device)
            for link in round_plan.network_links
        }
        for edge in selected.graph_edges:
            if edge.source_partition not in node_ids or edge.target_partition not in node_ids:
                errors.append("graph_edge_unknown_node")
                continue
            adjacency[edge.source_partition].add(edge.target_partition)
            source = node_partitions.get(edge.source_partition)
            target = node_partitions.get(edge.target_partition)
            if source is None or target is None:
                errors.append("graph_edge_unknown_partition")
            elif not self._has_required_network_link(
                source.device_id,
                target.device_id,
                edge.edge_type,
                link_pairs,
                is_training_plan,
            ):
                errors.append(
                    f"missing_network_link:{source.device_id}->{target.device_id}"
                )
        if is_training_plan:
            self._validate_training_graph_contract(
                plan.approved_execution_mode,
                selected.partitions,
                selected.graph_edges,
                errors,
            )
        if self._has_cycle(adjacency):
            errors.append("execution_graph_cycle")

        if (
            round_plan.constraints.max_end_to_end_latency_ms is not None
            and selected.estimated_total_latency_ms
            > round_plan.constraints.max_end_to_end_latency_ms
        ):
            errors.append("latency_slo_exceeded")
        if (
            round_plan.constraints.max_transfer_bytes is not None
            and selected.total_transfer_bytes
            > round_plan.constraints.max_transfer_bytes
        ):
            errors.append("max_transfer_bytes_exceeded")
        return self._result(errors)

    def _validate_v2(
        self,
        request: PartitionPlanningRequest,
        plan: PartitionExecutionPlan,
    ) -> PartitionValidationResult:
        errors: list[str] = []
        try:
            normalized = self._common_processor.process(request)
        except PartitionContractError as exc:
            return self._result([exc.code], checked_rules=self.V2_CHECKED_RULES)

        round_plan = FederatedRoundPlan(
            job_id=normalized.job_id,
            model_id=normalized.model_id,
            execution_mode=normalized.approved_execution_mode,
            layers=normalized.layers,
            participants=normalized.participants,
            devices=normalized.devices,
            network_links=normalized.network_links,
            constraints=normalized.constraints,
        )
        errors.extend(self._validate_legacy(round_plan, plan).errors)

        envelope = request.envelope
        approved_mode = request.approved_execution_mode
        if not envelope.approved_by or not envelope.approval_ref:
            errors.append("approval_provenance_missing")
        if (
            approved_mode is None
            or not approved_mode.approved
            or not approved_mode.approved_by
            or not approved_mode.approval_ref
        ):
            errors.append("approved_mode_provenance_missing")
        elif plan.approved_execution_mode != approved_mode.name:
            errors.append("approved_execution_mode_mismatch")

        if plan.plan_type != normalized.plan_type:
            errors.append("strategy_plan_type_mismatch")
        if plan.approved_model_version != normalized.approved_model_version:
            errors.append("approved_model_version_mismatch")
        if plan.input_snapshot_id != normalized.context_snapshot_id:
            errors.append("input_snapshot_id_mismatch")
        if plan.input_snapshot_hash != normalized.context_snapshot_hash:
            errors.append("input_snapshot_hash_mismatch")

        try:
            strategy = self._strategy_registry.resolve(
                normalized.plan_type, normalized.approved_execution_mode.name
            )
        except PartitionContractError as exc:
            errors.append(exc.code)
        else:
            if plan.strategy_id != strategy.strategy_id:
                errors.append("strategy_id_mismatch")
            if plan.strategy_version != strategy.strategy_version:
                errors.append("strategy_version_mismatch")

        if normalized.plan_type == "inference":
            self._validate_inference_graph_contract(plan, errors)
            self._validate_inference_slas(request, round_plan, plan, errors)

        expected_signature = self._deterministic_signature(normalized.input_signature, plan)
        if (
            not plan.deterministic_signature
            or plan.deterministic_signature != expected_signature
        ):
            errors.append("deterministic_signature_mismatch")
        return self._result(errors, checked_rules=self.V2_CHECKED_RULES)

    @staticmethod
    def _deterministic_signature(input_signature: str, plan: PartitionExecutionPlan) -> str:
        payload = {
            "input_signature": input_signature,
            "strategy_id": plan.strategy_id,
            "strategy_version": plan.strategy_version,
            "policy_version": plan.policy_version,
            "signature_version": "partition-selection-v2",
            "selection": (
                None if plan.selection is None else plan.selection.signature_provenance()
            ),
            "selected_candidate": (
                None
                if plan.selected_candidate is None
                else plan.selected_candidate.to_dict()
            ),
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_inference_graph_contract(
        plan: PartitionExecutionPlan, errors: list[str]
    ) -> None:
        selected = plan.selected_candidate
        if selected is None:
            return
        if any(
            edge.edge_type not in INFERENCE_FORWARD_EDGE_TYPES
            for edge in selected.graph_edges
        ):
            errors.append("inference_graph_forward_contract_mismatch")
        if not _has_inference_forward_chain(selected):
            errors.append("inference_graph_forward_path_missing")

    @staticmethod
    def _validate_inference_slas(
        request: PartitionPlanningRequest,
        round_plan: FederatedRoundPlan,
        plan: PartitionExecutionPlan,
        errors: list[str],
    ) -> None:
        selected = plan.selected_candidate
        latency_slo = getattr(request.plan, "latency_slo_ms", None)
        if (
            latency_slo is not None
            and selected is not None
            and selected.estimated_total_latency_ms > latency_slo
        ):
            errors.append("latency_slo_exceeded")

        throughput_capacity = predicted_inference_throughput_capacity(request, plan)
        if throughput_capacity is None:
            errors.append("predicted_throughput_unverifiable")
        elif throughput_capacity < request.plan.minimum_throughput_rps:
            errors.append("predicted_throughput_capacity_exceeded")

        availability_feasibility = predicted_snapshot_availability_feasibility(
            round_plan, plan
        )
        if availability_feasibility is None:
            errors.append("snapshot_availability_unverifiable")
        elif availability_feasibility < request.plan.availability_target:
            errors.append("snapshot_availability_target_not_met")

    def _result(
        self,
        errors: list[str],
        *,
        checked_rules: tuple[str, ...] | None = None,
    ) -> PartitionValidationResult:
        unique_errors = tuple(dict.fromkeys(errors))
        return PartitionValidationResult(
            valid=not unique_errors,
            errors=unique_errors,
            checked_rules=checked_rules or self.CHECKED_RULES,
        )

    @staticmethod
    def _graph_node_partitions(
        partitions: tuple[Any, ...], is_training_plan: bool, approved_mode: str
    ) -> dict[str, Any]:
        if not is_training_plan:
            return {partition.partition_id: partition for partition in partitions}
        if not partitions:
            return {}
        if approved_mode == "federated_learning":
            return {
                **{partition.partition_id: partition for partition in partitions},
                "aggregation": partitions[0],
            }
        phase_nodes = {
            f"{partition.partition_id}:{phase}": partition
            for partition in partitions
            for phase in ("forward", "backward")
        }
        return {**phase_nodes, "aggregation": partitions[0]}

    @staticmethod
    def _has_required_network_link(
        source_device: str,
        target_device: str,
        edge_type: str,
        link_pairs: set[tuple[str, str]],
        is_training_plan: bool,
    ) -> bool:
        if source_device == target_device:
            return True
        if (source_device, target_device) in link_pairs:
            return True
        return (
            is_training_plan
            and edge_type == "backward"
            and (target_device, source_device) in link_pairs
        )

    def _validate_training_graph_contract(
        self,
        approved_mode: str,
        partitions: tuple[Any, ...],
        graph_edges: tuple[Any, ...],
        errors: list[str],
    ) -> None:
        if approved_mode not in self.TRAINING_GRAPH_MODES:
            errors.append("training_graph_mode_not_supported")
            return
        if approved_mode == "federated_learning":
            expected_edges = {
                (partition.partition_id, "aggregation", "aggregation")
                for partition in partitions[1:]
            }
            actual_edges = {
                (edge.source_partition, edge.target_partition, edge.edge_type)
                for edge in graph_edges
            }
            if actual_edges != expected_edges:
                errors.append("federated_aggregation_graph_contract_mismatch")
            return
        expected_edges = {
            *(
                (
                    f"{source.partition_id}:forward",
                    f"{target.partition_id}:forward",
                    "forward",
                )
                for source, target in zip(partitions, partitions[1:])
            ),
            *(
                (
                    f"{target.partition_id}:backward",
                    f"{source.partition_id}:backward",
                    "backward",
                )
                for source, target in zip(partitions, partitions[1:])
            ),
        }
        if partitions:
            expected_edges.update(
                {
                    (
                        f"{partitions[-1].partition_id}:forward",
                        f"{partitions[-1].partition_id}:backward",
                        "gradient",
                    ),
                    (
                        f"{partitions[0].partition_id}:backward",
                        "aggregation",
                        "aggregation",
                    ),
                }
            )
        actual_edges = {
            (edge.source_partition, edge.target_partition, edge.edge_type)
            for edge in graph_edges
        }
        if actual_edges != expected_edges:
            errors.append("training_graph_phase_contract_mismatch")

    @staticmethod
    def _has_cycle(adjacency: dict[str, set[str]]) -> bool:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(target) for target in adjacency.get(node, ())):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in adjacency)


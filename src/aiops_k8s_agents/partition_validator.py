from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionExecutionPlan,
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

    def validate(
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
        if actual_layer_names != expected_layer_names:
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
            selected.partitions, is_training_plan
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

    def _result(self, errors: list[str]) -> PartitionValidationResult:
        unique_errors = tuple(dict.fromkeys(errors))
        return PartitionValidationResult(
            valid=not unique_errors,
            errors=unique_errors,
            checked_rules=self.CHECKED_RULES,
        )

    @staticmethod
    def _graph_node_partitions(
        partitions: tuple[Any, ...], is_training_plan: bool
    ) -> dict[str, Any]:
        if not is_training_plan:
            return {partition.partition_id: partition for partition in partitions}
        if not partitions:
            return {}
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

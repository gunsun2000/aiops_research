from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from orchestrator_agent.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from orchestrator_agent.partition_coordination import PartitionPlanningRequest
from orchestrator_agent.partition_models import (
    ExecutionGraphEdge,
    ExecutionGraphNode,
    FederatedRoundPlan,
)
from orchestrator_agent.partition_validator import PartitionPlanValidator


ROOT = Path(__file__).resolve().parents[1]


def round_plan_and_execution_plan():
    round_plan = FederatedRoundPlan.from_dict(
        json.loads(
            (ROOT / "config/examples/model_partition_job.json").read_text(
                encoding="utf-8"
            )
        )
    )
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    plan = ModelPartitionOrchestrationAgent(
        policy, plan_id_factory=lambda: "validator-plan"
    ).plan(round_plan)
    return round_plan, plan


def v2_request_and_execution_plan(example_name: str = "model_partition_inference_v2.json"):
    request = PartitionPlanningRequest.from_dict(
        json.loads((ROOT / "config/examples" / example_name).read_text(encoding="utf-8"))
    )
    if request.envelope.plan_type == "inference":
        request = replace(
            request,
            plan=replace(
                request.plan,
                latency_slo_ms=500.0,
                constraints=replace(
                    request.plan.constraints, max_end_to_end_latency_ms=500.0
                ),
            ),
        )
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    plan = ModelPartitionOrchestrationAgent(
        policy, plan_id_factory=lambda: "validator-v2-plan"
    ).plan_request(request)
    return request, plan


def test_validator_accepts_complete_selected_plan():
    round_plan, plan = round_plan_and_execution_plan()

    result = PartitionPlanValidator().validate(round_plan, plan)

    assert result.valid is True
    assert result.errors == ()
    assert "layer_coverage" in result.checked_rules
    assert "execution_graph_dag" in result.checked_rules


def test_validator_accepts_phase_distinct_training_dag():
    request = PartitionPlanningRequest.from_dict(
        json.loads(
            (ROOT / "config/examples/model_partition_training_v2.json").read_text(
                encoding="utf-8"
            )
        )
    )
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    agent = ModelPartitionOrchestrationAgent(
        policy, plan_id_factory=lambda: "validator-training-plan"
    )
    plan = agent.plan_request(request)

    result = PartitionPlanValidator().validate(request, plan)

    assert result.valid is True
    assert "graph_node_partition_mismatch" not in result.errors
    assert "graph_edge_unknown_partition" not in result.errors
    assert "execution_graph_cycle" not in result.errors


def test_validator_accepts_complete_v2_inference_plan():
    request, plan = v2_request_and_execution_plan()

    result = PartitionPlanValidator().validate(request, plan)

    assert result.valid is True
    assert "deterministic_signature" in result.checked_rules
    assert "input_snapshot" in result.checked_rules


def test_validator_rejects_snapshot_hash_mismatch():
    request, plan = v2_request_and_execution_plan()

    result = PartitionPlanValidator().validate(
        request, replace(plan, input_snapshot_hash="0" * 64)
    )

    assert result.valid is False
    assert "input_snapshot_hash_mismatch" in result.errors


def test_validator_rejects_snapshot_id_and_direct_signature_mismatches():
    request, plan = v2_request_and_execution_plan()

    result = PartitionPlanValidator().validate(
        request,
        replace(
            plan,
            input_snapshot_id="snapshot-tampered",
            deterministic_signature="0" * 64,
        ),
    )

    assert result.valid is False
    assert "input_snapshot_id_mismatch" in result.errors
    assert "deterministic_signature_mismatch" in result.errors


def test_validator_rejects_tampered_selected_candidate_signature():
    request, plan = v2_request_and_execution_plan()
    selected = plan.selected_candidate
    assert selected is not None

    result = PartitionPlanValidator().validate(
        request,
        replace(
            plan,
            selected_candidate=replace(
                selected,
                estimated_total_latency_ms=selected.estimated_total_latency_ms + 1.0,
            ),
        ),
    )

    assert result.valid is False
    assert "deterministic_signature_mismatch" in result.errors


def test_validator_rejects_strategy_plan_type_mismatch():
    request, plan = v2_request_and_execution_plan("model_partition_training_v2.json")
    _, inference_plan = v2_request_and_execution_plan()

    result = PartitionPlanValidator().validate(request, inference_plan)

    assert result.valid is False
    assert "strategy_plan_type_mismatch" in result.errors


def test_validator_rejects_approved_mode_model_and_strategy_mismatches():
    request, plan = v2_request_and_execution_plan()

    result = PartitionPlanValidator().validate(
        request,
        replace(
            plan,
            approved_execution_mode="pipeline_parallel",
            approved_model_version="model-version-tampered",
            strategy_id="strategy-tampered",
            strategy_version="strategy-version-tampered",
        ),
    )

    assert result.valid is False
    assert "approved_execution_mode_mismatch" in result.errors
    assert "approved_model_version_mismatch" in result.errors
    assert "strategy_id_mismatch" in result.errors
    assert "strategy_version_mismatch" in result.errors


def test_validator_rejects_non_forward_inference_graph_edges():
    request, plan = v2_request_and_execution_plan()
    selected = plan.selected_candidate
    assert selected is not None
    edge = selected.graph_edges[0]

    result = PartitionPlanValidator().validate(
        request,
        replace(
            plan,
            selected_candidate=replace(
                selected,
                graph_edges=(replace(edge, edge_type="backward"), *selected.graph_edges[1:]),
            ),
        ),
    )

    assert result.valid is False
    assert "inference_graph_forward_contract_mismatch" in result.errors


def test_validator_rejects_disconnected_inference_graph_with_recomputed_signature():
    request, plan = v2_request_and_execution_plan()
    selected = plan.selected_candidate
    assert selected is not None
    broken = replace(plan, selected_candidate=replace(selected, graph_edges=()))
    signed_broken = replace(
        broken,
        deterministic_signature=PartitionPlanValidator._deterministic_signature(
            ModelPartitionOrchestrationAgent(
                ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
            )._common_processor.process(request).input_signature,
            broken,
        ),
    )

    result = PartitionPlanValidator().validate(request, signed_broken)

    assert result.valid is False
    assert "inference_graph_forward_path_missing" in result.errors
    assert "deterministic_signature_mismatch" not in result.errors


def test_validator_rejects_inference_throughput_target_above_predicted_capacity():
    request, _ = v2_request_and_execution_plan()
    request = replace(
        request,
        plan=replace(request.plan, minimum_throughput_rps=1_000_000.0),
    )
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    plan = ModelPartitionOrchestrationAgent(policy).plan_request(request)

    result = PartitionPlanValidator().validate(request, plan)

    assert result.valid is False
    assert "predicted_throughput_capacity_exceeded" in result.errors


def test_validator_rejects_inference_without_positive_concurrency_capacity_input():
    request, _ = v2_request_and_execution_plan()
    request = replace(
        request,
        plan=replace(request.plan, concurrency_policy={"max_requests": 0}),
    )
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    plan = ModelPartitionOrchestrationAgent(policy).plan_request(request)

    result = PartitionPlanValidator().validate(request, plan)

    assert result.valid is False
    assert "predicted_throughput_unverifiable" in result.errors


def test_validator_rejects_snapshot_availability_target_after_topology_failure():
    request, plan = v2_request_and_execution_plan()
    selected = plan.selected_candidate
    assert selected is not None
    broken = replace(
        plan,
        selected_candidate=replace(
            selected,
            partitions=(
                replace(selected.partitions[0], device_id="offline-device"),
                *selected.partitions[1:],
            ),
        ),
    )
    signed_broken = replace(
        broken,
        deterministic_signature=PartitionPlanValidator._deterministic_signature(
            ModelPartitionOrchestrationAgent(
                ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
            )._common_processor.process(request).input_signature,
            broken,
        ),
    )

    result = PartitionPlanValidator().validate(request, signed_broken)

    assert result.valid is False
    assert "snapshot_availability_target_not_met" in result.errors


def test_validator_marks_snapshot_availability_unverifiable_without_candidate():
    request, plan = v2_request_and_execution_plan()
    unsigned = replace(plan, selected_candidate=None)
    signed = replace(
        unsigned,
        deterministic_signature=PartitionPlanValidator._deterministic_signature(
            ModelPartitionOrchestrationAgent(
                ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
            )._common_processor.process(request).input_signature,
            unsigned,
        ),
    )

    result = PartitionPlanValidator().validate(request, signed)

    assert result.valid is False
    assert "snapshot_availability_unverifiable" in result.errors


def test_validator_rejects_training_graph_missing_required_aggregation_edge():
    request = PartitionPlanningRequest.from_dict(
        json.loads(
            (ROOT / "config/examples/model_partition_training_v2.json").read_text(
                encoding="utf-8"
            )
        )
    )
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    agent = ModelPartitionOrchestrationAgent(
        policy, plan_id_factory=lambda: "validator-training-plan"
    )
    normalized = agent._common_processor.process(request)
    round_plan = agent._round_plan_from_normalized(normalized)
    plan = agent.plan_request(request)
    selected = plan.selected_candidate
    assert selected is not None
    broken_plan = replace(
        plan,
        selected_candidate=replace(
            selected,
            graph_edges=tuple(
                edge for edge in selected.graph_edges if edge.edge_type != "aggregation"
            ),
        ),
    )

    result = PartitionPlanValidator().validate(round_plan, broken_plan)

    assert result.valid is False
    assert "training_graph_phase_contract_mismatch" in result.errors
    assert "execution_graph_cycle" not in result.errors


def test_validator_detects_duplicate_and_missing_layers():
    round_plan, plan = round_plan_and_execution_plan()
    selected = plan.selected_candidate
    assert selected is not None
    first, second = selected.partitions
    broken_second = replace(
        second,
        layer_names=(first.layer_names[-1], *second.layer_names[1:]),
    )
    broken_plan = replace(
        plan,
        selected_candidate=replace(selected, partitions=(first, broken_second)),
    )

    result = PartitionPlanValidator().validate(round_plan, broken_plan)

    assert result.valid is False
    assert "layer_coverage_mismatch" in result.errors


def test_validator_detects_unknown_device_and_graph_node_mismatch():
    round_plan, plan = round_plan_and_execution_plan()
    selected = plan.selected_candidate
    assert selected is not None
    broken_partition = replace(selected.partitions[0], device_id="unknown-device")
    broken_plan = replace(
        plan,
        selected_candidate=replace(
            selected,
            partitions=(broken_partition, *selected.partitions[1:]),
        ),
    )

    result = PartitionPlanValidator().validate(round_plan, broken_plan)

    assert "unknown_partition_device:unknown-device" in result.errors
    assert "graph_node_partition_mismatch" in result.errors


def test_validator_detects_execution_graph_cycle():
    round_plan, plan = round_plan_and_execution_plan()
    selected = plan.selected_candidate
    assert selected is not None
    reverse = ExecutionGraphEdge(
        source_partition="partition-2",
        target_partition="partition-1",
        transfer_bytes=100,
        estimated_transfer_ms=1.0,
    )
    broken_plan = replace(
        plan,
        selected_candidate=replace(
            selected, graph_edges=(*selected.graph_edges, reverse)
        ),
    )

    result = PartitionPlanValidator().validate(round_plan, broken_plan)

    assert "execution_graph_cycle" in result.errors


def test_validator_detects_constraint_and_memory_estimate_tampering():
    round_plan, plan = round_plan_and_execution_plan()
    selected = plan.selected_candidate
    assert selected is not None
    first = replace(selected.partitions[0], memory_demand_bytes=1)
    broken_plan = replace(
        plan,
        selected_candidate=replace(
            selected,
            partitions=(first, *selected.partitions[1:]),
            estimated_total_latency_ms=9_999.0,
        ),
    )

    result = PartitionPlanValidator().validate(round_plan, broken_plan)

    assert "memory_demand_mismatch:partition-1" in result.errors
    assert "latency_slo_exceeded" in result.errors


def test_validator_rejects_safe_failure_for_downstream_handoff():
    round_plan, plan = round_plan_and_execution_plan()
    failed = replace(
        plan,
        selected_candidate=None,
        valid=False,
        human_review_required=True,
        errors=("no_feasible_partition",),
    )

    result = PartitionPlanValidator().validate(round_plan, failed)

    assert result.valid is False
    assert "selected_candidate_required" in result.errors


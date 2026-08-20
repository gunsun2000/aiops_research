from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_models import (
    ExecutionGraphEdge,
    ExecutionGraphNode,
    FederatedRoundPlan,
)
from aiops_k8s_agents.partition_validator import PartitionPlanValidator


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
    normalized = agent._common_processor.process(request)
    round_plan = agent._round_plan_from_normalized(normalized)
    plan = agent.plan_request(request)

    result = PartitionPlanValidator().validate(round_plan, plan)

    assert result.valid is True
    assert "graph_node_partition_mismatch" not in result.errors
    assert "graph_edge_unknown_partition" not in result.errors
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

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from orchestrator_agent.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from orchestrator_agent.partition_coordination import PartitionPlanningRequest
from orchestrator_agent.partition_models import PartitionContractError
from orchestrator_agent.partition_strategies import PartitionStrategyRegistry


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def training_request() -> PartitionPlanningRequest:
    payload = json.loads(
        (ROOT / "config/examples/model_partition_training_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return PartitionPlanningRequest.from_dict(payload)


@pytest.fixture
def orchestrator() -> ModelPartitionOrchestrationAgent:
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    return ModelPartitionOrchestrationAgent(
        policy,
        plan_id_factory=lambda: "partition-plan-training-test",
    )


def test_training_strategy_builds_phase_distinct_forward_and_backward_dag(
    training_request: PartitionPlanningRequest,
    orchestrator: ModelPartitionOrchestrationAgent,
) -> None:
    plan = orchestrator.plan_request(training_request)

    selected = plan.selected_candidate
    assert selected is not None
    edge_types = {edge.edge_type for edge in selected.graph_edges}
    assert {"forward", "backward", "gradient", "aggregation"}.issubset(edge_types)
    assert selected.estimated_step_time_ms > 0
    assert selected.gradient_transfer_bytes > 0
    assert selected.maximum_load_imbalance >= 0
    assert {node.partition_id for node in selected.graph_nodes} == {
        "partition-1:forward",
        "partition-2:forward",
        "partition-2:backward",
        "partition-1:backward",
        "aggregation",
    }


def test_training_strategy_excludes_forbidden_split_boundary(
    training_request: PartitionPlanningRequest,
    orchestrator: ModelPartitionOrchestrationAgent,
) -> None:
    plan = orchestrator.plan_request(training_request)

    assert all(
        2 not in candidate.split_points
        for candidate in (plan.selected_candidate, *plan.alternative_candidates)
        if candidate is not None
    )


def test_training_resilience_weight_changes_predicted_candidate_score(
    training_request: PartitionPlanningRequest,
    orchestrator: ModelPartitionOrchestrationAgent,
) -> None:
    plan = orchestrator.plan_request(training_request)
    selected = plan.selected_candidate
    assert selected is not None
    normalized = orchestrator._common_processor.process(training_request)
    strategy = PartitionStrategyRegistry.default().resolve(
        normalized.plan_type,
        normalized.approved_execution_mode.name,
    )
    intent = strategy.build_partition_intent(normalized)
    performance_only = replace(
        intent,
        objective_weights=(
            ("step_time", 1.0),
            ("load_balance", 0.0),
            ("memory_pressure", 0.0),
            ("communication", 0.0),
            ("resilience", 0.0),
        ),
    )
    resilience_only = replace(
        intent,
        objective_weights=(
            ("step_time", 0.0),
            ("load_balance", 0.0),
            ("memory_pressure", 0.0),
            ("communication", 0.0),
            ("resilience", 1.0),
        ),
    )

    performance_score = orchestrator._score_training(
        selected.estimated_step_time_ms,
        selected.maximum_load_imbalance,
        selected.maximum_memory_pressure,
        selected.total_transfer_bytes,
        selected.predicted_resilience_risk,
        performance_only,
    )
    resilience_score = orchestrator._score_training(
        selected.estimated_step_time_ms,
        selected.maximum_load_imbalance,
        selected.maximum_memory_pressure,
        selected.total_transfer_bytes,
        selected.predicted_resilience_risk,
        resilience_only,
    )

    assert 0.0 <= selected.predicted_resilience_risk <= 1.0
    assert performance_score != resilience_score
    assert resilience_score == selected.predicted_resilience_risk


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), -float("inf")])
def test_training_strategy_rejects_non_finite_policy_weight(tmp_path: Path, weight: float) -> None:
    policy = json.loads(
        (ROOT / "config/model_partition_policy.json").read_text(encoding="utf-8")
    )
    policy["strategy_policies"]["training-partition-v1"]["objectives"][
        "step_time"
    ] = weight
    path = tmp_path / "model_partition_policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(PartitionContractError) as error:
        PartitionStrategyRegistry.default(path)

    assert error.value.code == "invalid_partition_policy"


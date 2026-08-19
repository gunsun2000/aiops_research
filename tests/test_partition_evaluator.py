from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_evaluator import (
    ObservedPartitionMetrics,
    PartitionPlanEvaluator,
)
from aiops_k8s_agents.partition_models import FederatedRoundPlan
from aiops_k8s_agents.partition_validator import (
    PartitionPlanValidator,
    PartitionValidationResult,
)


ROOT = Path(__file__).resolve().parents[1]


def evaluated_inputs():
    round_plan = FederatedRoundPlan.from_dict(
        json.loads(
            (ROOT / "config/examples/model_partition_job.json").read_text(
                encoding="utf-8"
            )
        )
    )
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    plan = ModelPartitionOrchestrationAgent(
        policy, plan_id_factory=lambda: "evaluation-plan"
    ).plan(round_plan)
    validation = PartitionPlanValidator().validate(round_plan, plan)
    return round_plan, policy, plan, validation


def test_predicted_reward_is_bounded_and_labeled():
    round_plan, policy, plan, validation = evaluated_inputs()

    result = PartitionPlanEvaluator(policy).evaluate(
        round_plan, plan, validation
    )

    assert -1.0 <= result.reward <= 1.0
    assert result.reward > 0
    assert result.evidence_level == "predicted"
    assert result.estimated is True
    assert set(result.components) == {
        "constraint_satisfaction",
        "latency_efficiency",
        "memory_safety",
        "communication_efficiency",
    }


def test_invalid_plan_cannot_receive_positive_reward():
    round_plan, policy, plan, _ = evaluated_inputs()
    invalid = replace(plan, valid=False)
    validation = PartitionValidationResult(
        valid=False,
        errors=("partition_validation_failed",),
        checked_rules=("plan_identity",),
    )

    result = PartitionPlanEvaluator(policy).evaluate(
        round_plan, invalid, validation
    )

    assert result.reward <= 0.0


def test_observed_metrics_are_labeled_and_reduce_reward_when_performance_worsens():
    round_plan, policy, plan, validation = evaluated_inputs()
    evaluator = PartitionPlanEvaluator(policy)
    predicted = evaluator.evaluate(round_plan, plan, validation)

    observed = evaluator.evaluate(
        round_plan,
        plan,
        validation,
        observed=ObservedPartitionMetrics(
            latency_ms=850.0,
            maximum_memory_pressure=0.85,
            total_transfer_bytes=4_500_000,
        ),
    )

    assert observed.evidence_level == "observed"
    assert observed.estimated is False
    assert observed.reward < predicted.reward

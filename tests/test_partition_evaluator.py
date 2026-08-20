from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_evaluator import (
    ObservedPartitionMetrics,
    PartitionPlanEvaluator,
)
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
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


def v2_evaluated_inputs(example_name: str):
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
        policy, plan_id_factory=lambda: "evaluation-v2-plan"
    ).plan_request(request)
    validation = PartitionPlanValidator().validate(request, plan)
    return request, policy, plan, validation


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
            source="runtime-monitor",
            observed_at="2026-08-20T09:30:00Z",
        ),
    )

    assert observed.evidence_level == "observed"
    assert observed.estimated is False
    assert observed.reward < predicted.reward


def test_inference_evaluation_is_explicitly_predicted():
    request, policy, plan, validation = v2_evaluated_inputs(
        "model_partition_inference_v2.json"
    )

    result = PartitionPlanEvaluator(policy).evaluate(request, plan, validation)

    assert result.evidence_level == "predicted"
    assert result.estimated is True
    assert result.label == "Estimated reward (predicted evidence)"
    assert "latency_efficiency" in result.components
    assert result.confidence == plan.confidence
    assert result.strategy_id == plan.strategy_id


def test_training_evaluation_uses_step_time_and_balance():
    request, policy, plan, validation = v2_evaluated_inputs(
        "model_partition_training_v2.json"
    )

    result = PartitionPlanEvaluator(policy).evaluate(request, plan, validation)

    assert result.evidence_level == "predicted"
    assert "step_time_efficiency" in result.components
    assert "load_balance" in result.components
    assert "resilience" in result.components


def test_observed_metrics_require_source_and_timestamp():
    request, policy, plan, validation = v2_evaluated_inputs(
        "model_partition_inference_v2.json"
    )

    result = PartitionPlanEvaluator(policy).evaluate(
        request,
        plan,
        validation,
        observed=ObservedPartitionMetrics(
            latency_ms=12.0,
            maximum_memory_pressure=0.2,
            total_transfer_bytes=2_000,
        ),
    )

    assert result.evidence_level == "predicted"
    assert result.estimated is True


@pytest.mark.parametrize(
    "payload",
    (
        {
            "latency_ms": float("nan"),
            "maximum_memory_pressure": 0.2,
            "total_transfer_bytes": 2_000,
            "source": "runtime-monitor",
            "observed_at": "2026-08-20T09:30:00Z",
        },
        {
            "latency_ms": float("inf"),
            "maximum_memory_pressure": 0.2,
            "total_transfer_bytes": 2_000,
            "source": "runtime-monitor",
            "observed_at": "2026-08-20T09:30:00Z",
        },
        {
            "latency_ms": -1.0,
            "maximum_memory_pressure": 0.2,
            "total_transfer_bytes": 2_000,
            "source": "runtime-monitor",
            "observed_at": "2026-08-20T09:30:00Z",
        },
        {
            "latency_ms": 12.0,
            "maximum_memory_pressure": -0.2,
            "total_transfer_bytes": 2_000,
            "source": "runtime-monitor",
            "observed_at": "2026-08-20T09:30:00Z",
        },
        {
            "latency_ms": 12.0,
            "maximum_memory_pressure": 0.2,
            "total_transfer_bytes": -2_000,
            "source": "runtime-monitor",
            "observed_at": "2026-08-20T09:30:00Z",
        },
    ),
)
def test_runtime_evidence_from_dict_rejects_nonfinite_and_negative_metrics(payload):
    with pytest.raises(ValueError, match="runtime evidence"):
        ObservedPartitionMetrics.from_dict(payload)


@pytest.mark.parametrize(
    ("source", "observed_at"),
    (
        ("", "2026-08-20T09:30:00Z"),
        ("runtime-monitor", ""),
        ("runtime-monitor", "not-a-timestamp"),
    ),
)
def test_runtime_evidence_from_dict_requires_complete_valid_provenance(
    source, observed_at
):
    with pytest.raises(ValueError, match="runtime evidence"):
        ObservedPartitionMetrics.from_dict(
            {
                "latency_ms": 12.0,
                "maximum_memory_pressure": 0.2,
                "total_transfer_bytes": 2_000,
                "source": source,
                "observed_at": observed_at,
            }
        )


def test_evaluate_rejects_invalid_direct_runtime_evidence():
    request, policy, plan, validation = v2_evaluated_inputs(
        "model_partition_inference_v2.json"
    )

    with pytest.raises(ValueError, match="runtime evidence"):
        PartitionPlanEvaluator(policy).evaluate(
            request,
            plan,
            validation,
            observed=ObservedPartitionMetrics(
                latency_ms=float("nan"),
                maximum_memory_pressure=0.2,
                total_transfer_bytes=2_000,
                source="runtime-monitor",
                observed_at="2026-08-20T09:30:00Z",
            ),
        )


def test_inference_evaluation_labels_throughput_and_snapshot_feasibility_as_predicted():
    request, policy, plan, validation = v2_evaluated_inputs(
        "model_partition_inference_v2.json"
    )

    result = PartitionPlanEvaluator(policy).evaluate(request, plan, validation)

    assert result.metrics["predicted_throughput_capacity_rps"] > 0
    assert result.metrics["predicted_snapshot_availability_feasibility"] == 1.0
    assert result.metrics["throughput_capacity_evidence"] == "predicted"
    assert result.metrics["availability_evidence"] == "predicted_snapshot_feasibility"

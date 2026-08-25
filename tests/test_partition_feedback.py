from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orchestrator_agent.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from orchestrator_agent.partition_feedback import (
    PartitionFeedbackAnalyzer,
    PartitionRuntimeFeedback,
)
from orchestrator_agent.partition_models import (
    FederatedRoundPlan,
    PartitionContractError,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def previous_plan():
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    return ModelPartitionOrchestrationAgent(
        policy, plan_id_factory=lambda: "partition-plan-v1"
    ).plan(FederatedRoundPlan.from_dict(payload))


@pytest.fixture
def feedback_payload(previous_plan):
    return {
        "signal": "latency_slo_violation",
        "source": "runtime-monitor",
        "reason": "observed feedback requires a bounded replan",
        "received_at": "2026-08-20T00:00:00+00:00",
        "plan_id": previous_plan.plan_id,
        "plan_version": previous_plan.plan_version,
        "device_id": "edge-cpu-01",
        "source_device": "edge-cpu-01",
        "target_device": "gpu-worker-01",
        "candidate_id": "candidate-rejected-by-placement",
    }


@pytest.mark.parametrize(
    ("signal", "expected_exclusion"),
    [
        ("device_unavailable", "device"),
        ("transfer_failure", "link"),
        ("latency_slo_violation", "split"),
        ("placement_rejected", "candidate"),
    ],
)
def test_feedback_maps_to_bounded_exclusion(
    feedback_payload, previous_plan, signal, expected_exclusion
):
    feedback_payload["signal"] = signal

    directive = PartitionFeedbackAnalyzer().analyze(
        PartitionRuntimeFeedback.from_dict(feedback_payload), previous_plan
    )

    assert directive.exclusion_type == expected_exclusion


@pytest.mark.parametrize("field", ["source", "reason", "received_at", "plan_id"])
def test_feedback_requires_provenance_fields(feedback_payload, field):
    feedback_payload.pop(field)

    with pytest.raises(PartitionContractError) as error:
        PartitionRuntimeFeedback.from_dict(feedback_payload)

    assert error.value.code == "feedback_context_required"


def test_feedback_rejects_unknown_signals(feedback_payload):
    feedback_payload["signal"] = "observed_runtime_miracle"

    with pytest.raises(PartitionContractError) as error:
        PartitionRuntimeFeedback.from_dict(feedback_payload)

    assert error.value.code == "unsupported_feedback_signal"


def test_feedback_requires_signal_specific_device_or_link_identifiers(feedback_payload):
    device_feedback = copy.deepcopy(feedback_payload)
    device_feedback["signal"] = "device_unavailable"
    device_feedback.pop("device_id")
    link_feedback = copy.deepcopy(feedback_payload)
    link_feedback["signal"] = "transfer_failure"
    link_feedback.pop("target_device")

    for payload in (device_feedback, link_feedback):
        with pytest.raises(PartitionContractError) as error:
            PartitionRuntimeFeedback.from_dict(payload)

        assert error.value.code == "feedback_context_required"


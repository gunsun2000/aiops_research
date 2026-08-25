from __future__ import annotations

import pytest

from orchestrator_agent.partition_models import (
    ExecutionGraphEdge,
    ExecutionGraphNode,
    FederatedRoundPlan,
    LogicalPartition,
    PartitionCandidate,
    PartitionContractError,
    PartitionExecutionPlan,
    PartitionFailure,
)
from orchestrator_agent.partition_ranking_models import (
    CandidateRankingEntry,
    CandidateSelection,
    SelectionMode,
)


def example_payload() -> dict:
    return {
        "job_id": "job-model-partition-001",
        "model_id": "transformer-6-layer",
        "execution_mode": {
            "name": "split_learning",
            "approved": True,
            "approved_by": "FederatedCoordinationAgent",
            "approval_ref": "round-plan-001",
        },
        "layers": [
            {
                "name": f"layer-{index}",
                "compute_units": 100.0 * index,
                "parameter_bytes": 1_000 * index,
                "activation_bytes": 500 * index,
                "working_memory_bytes": 2_000 * index,
            }
            for index in range(1, 7)
        ],
        "participants": ["edge-a", "gpu-b"],
        "devices": [
            {
                "device_id": "edge-a",
                "device_type": "cpu",
                "compute_units_per_second": 1_000.0,
                "memory_capacity_bytes": 100_000,
                "memory_available_bytes": 90_000,
            },
            {
                "device_id": "gpu-b",
                "device_type": "gpu",
                "compute_units_per_second": 4_000.0,
                "memory_capacity_bytes": 100_000,
                "memory_available_bytes": 95_000,
            },
        ],
        "network_links": [
            {
                "source_device": "edge-a",
                "target_device": "gpu-b",
                "bandwidth_bytes_per_second": 1_000_000.0,
                "latency_ms": 2.0,
            }
        ],
        "constraints": {
            "max_end_to_end_latency_ms": 1_000.0,
            "max_transfer_bytes": 10_000,
            "minimum_memory_headroom_ratio": 0.1,
        },
    }


def test_round_plan_parses_and_serializes_canonical_input():
    payload = example_payload()

    plan = FederatedRoundPlan.from_dict(payload)

    assert plan.job_id == "job-model-partition-001"
    assert plan.execution_mode.approval_ref == "round-plan-001"
    assert tuple(layer.name for layer in plan.layers) == tuple(
        f"layer-{index}" for index in range(1, 7)
    )
    assert plan.to_dict() == payload


def test_round_plan_requires_upstream_mode_approval():
    payload = example_payload()
    payload["execution_mode"]["approved"] = False

    with pytest.raises(PartitionContractError, match="approved_mode_required"):
        FederatedRoundPlan.from_dict(payload)


@pytest.mark.parametrize("field", ["approved_by", "approval_ref"])
def test_round_plan_requires_mode_approval_provenance(field):
    payload = example_payload()
    payload["execution_mode"][field] = ""

    with pytest.raises(PartitionContractError, match="approval_provenance_required"):
        FederatedRoundPlan.from_dict(payload)


def test_round_plan_rejects_unknown_participant_device():
    payload = example_payload()
    payload["participants"] = ["edge-a", "missing-device"]

    with pytest.raises(PartitionContractError, match="unknown_participant"):
        FederatedRoundPlan.from_dict(payload)


def test_round_plan_rejects_missing_adjacent_network_link():
    payload = example_payload()
    payload["network_links"] = []

    with pytest.raises(PartitionContractError, match="missing_network_link"):
        FederatedRoundPlan.from_dict(payload)


def test_round_plan_requires_enough_layers_for_participants():
    payload = example_payload()
    payload["layers"] = payload["layers"][:2]
    payload["participants"] = ["edge-a", "gpu-b", "gpu-c"]
    payload["devices"].append(
        {
            "device_id": "gpu-c",
            "device_type": "gpu",
            "compute_units_per_second": 5_000.0,
            "memory_capacity_bytes": 100_000,
            "memory_available_bytes": 95_000,
        }
    )
    payload["network_links"].append(
        {
            "source_device": "gpu-b",
            "target_device": "gpu-c",
            "bandwidth_bytes_per_second": 1_000_000.0,
            "latency_ms": 2.0,
        }
    )

    with pytest.raises(PartitionContractError, match="insufficient_layers"):
        FederatedRoundPlan.from_dict(payload)


def test_round_plan_rejects_invalid_memory_snapshot():
    payload = example_payload()
    payload["devices"][0]["memory_available_bytes"] = 100_001

    with pytest.raises(PartitionContractError, match="invalid_memory_snapshot"):
        FederatedRoundPlan.from_dict(payload)


def test_round_plan_rejects_duplicate_layer_names():
    payload = example_payload()
    payload["layers"][1]["name"] = payload["layers"][0]["name"]

    with pytest.raises(PartitionContractError, match="duplicate_layer"):
        FederatedRoundPlan.from_dict(payload)


def test_execution_plan_serializes_selected_candidate_and_safe_failure():
    partition = LogicalPartition(
        partition_id="partition-1",
        device_id="edge-a",
        layer_names=("layer-1", "layer-2"),
        compute_units=300.0,
        memory_demand_bytes=8_000,
    )
    candidate = PartitionCandidate(
        split_points=(2,),
        partitions=(partition,),
        graph_nodes=(ExecutionGraphNode("partition-1", "edge-a"),),
        graph_edges=(),
        estimated_compute_ms=300.0,
        estimated_transfer_ms=0.0,
        estimated_total_latency_ms=300.0,
        total_transfer_bytes=0,
        maximum_memory_pressure=0.08,
        valid=True,
        rejection_reasons=(),
        score=0.25,
    )
    selected = PartitionExecutionPlan(
        plan_id="partition-plan-001",
        job_id="job-001",
        model_id="model-001",
        approved_execution_mode="split_learning",
        policy_version="partition-policy-v1",
        selected_candidate=candidate,
        alternative_candidates=(),
        rationale="lowest deterministic score",
        valid=True,
        human_review_required=False,
        errors=(),
        selection=CandidateSelection(
            mode=SelectionMode.DETERMINISTIC,
            active_ranker_id="deterministic-policy-ranker",
            active_ranker_version="1.0",
            baseline_selected_candidate_key="candidate-key-1",
            learned_selected_candidate_key=None,
            final_selected_candidate_key="candidate-key-1",
            model_version=None,
            model_artifact_hash=None,
            feature_schema_version="partition-feature-v1",
            entries=(
                CandidateRankingEntry(
                    candidate_key="candidate-key-1",
                    baseline_score=0.25,
                    predicted_reward=None,
                    prediction_confidence=None,
                    rank=1,
                    eligible=True,
                ),
            ),
            confidence=1.0,
            fallback_used=False,
            fallback_reason=None,
            rationale=("deterministic policy ordering",),
        ),
    )
    failed = PartitionExecutionPlan.safe_failure(
        plan_id="partition-plan-002",
        job_id="job-001",
        model_id="model-001",
        approved_execution_mode="split_learning",
        policy_version="partition-policy-v1",
        errors=("no_feasible_partition",),
    )

    assert selected.to_dict()["selected_candidate"]["split_points"] == [2]
    assert selected.to_dict()["selection"]["mode"] == "deterministic"
    assert PartitionExecutionPlan.from_dict(selected.to_dict()) == selected
    assert failed.to_dict()["selected_candidate"] is None
    assert failed.human_review_required is True
    assert failed.valid is False


def test_execution_plan_reads_legacy_payload_with_v2_metadata_defaults():
    legacy_payload = PartitionExecutionPlan.safe_failure(
        plan_id="partition-plan-legacy",
        job_id="job-001",
        model_id="model-001",
        approved_execution_mode="split_learning",
        policy_version="partition-policy-v1",
        errors=("no_feasible_partition",),
    ).to_dict()
    for field in (
        "plan_version",
        "parent_plan_id",
        "plan_type",
        "approved_model_version",
        "strategy_id",
        "strategy_version",
        "input_snapshot_id",
        "input_snapshot_hash",
        "assumptions",
        "warnings",
        "confidence",
        "deterministic_signature",
        "handoff_status",
        "selection",
    ):
        legacy_payload.pop(field, None)

    plan = PartitionExecutionPlan.from_dict(legacy_payload)

    assert plan.plan_version == 1
    assert plan.parent_plan_id is None
    assert plan.plan_type == "inference"
    assert plan.approved_model_version == "legacy"
    assert plan.strategy_id == "legacy-partition-v1"
    assert plan.strategy_version == "1.0"
    assert plan.input_snapshot_id == "legacy-snapshot"
    assert plan.input_snapshot_hash == ""
    assert plan.assumptions == ()
    assert plan.warnings == ()
    assert plan.confidence == 0.0
    assert plan.deterministic_signature == ""
    assert plan.handoff_status == "not_ready"
    assert plan.selection is None


def test_partition_failure_requires_supported_signal():
    failure = PartitionFailure.from_dict(
        {
            "signal": "device_unavailable",
            "device_id": "edge-a",
            "source_device": "",
            "target_device": "",
            "details": "device stopped responding",
        }
    )
    assert failure.signal == "device_unavailable"

    with pytest.raises(PartitionContractError, match="unsupported_failure_signal"):
        PartitionFailure.from_dict({"signal": "unknown"})


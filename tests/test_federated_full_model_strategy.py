from __future__ import annotations

from aiops_k8s_agents.federated_coordination_adapter import (
    FederatedCoordinationPlanV04,
    FederatedCoordinationV04Adapter,
    ModelContext,
    ParticipantContext,
)
from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_context import (
    ModelBlock,
    ModelRegistryContext,
    ModelStructureProfile,
)
from aiops_k8s_agents.partition_models import NetworkLink, ResourceDevice
from aiops_k8s_agents.partition_validator import PartitionPlanValidator
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _request(*, memory_available: int = 8_000):
    payload = {
        "schema_version": "0.4",
        "task_type": "federated_training",
        "round_plan_id": "round-plan-fl-001",
        "job_id": "fl-training-001",
        "session_id": "session-001",
        "model_ref": {"model_id": "model-a", "version": 1},
        "learning_mode": {"selected": "FL", "fallback_order": ["SL"]},
        "coordination_mode": {"selected": "SYNC"},
        "federated_strategy": {
            "name": "FedAWARE",
            "aggregation_operator": "adaptive_weighted_aggregation",
            "parameter_ref": "fedaware-default-v1",
        },
        "candidate_participants": [
            {"client_id": "node-a", "priority": 1},
            {"client_id": "node-b", "priority": 2},
        ],
        "participation_policy": {
            "type": "SYNC",
            "candidate_pool_size": 2,
            "target_active": 2,
            "minimum_successful_participants": 1,
        },
    }
    participant_context = ParticipantContext(
        snapshot_id="prometheus-snapshot-fl",
        snapshot_version="prometheus-v1",
        collected_at="2026-08-24T12:00:00Z",
        devices=(
            ResourceDevice("node-a", "gpu", 200.0, 10_000, memory_available),
            ResourceDevice("node-b", "gpu", 180.0, 10_000, memory_available),
        ),
        network_links=(
            NetworkLink("node-a", "node-b", 1_000_000.0, 1.0),
            NetworkLink("node-b", "node-a", 1_000_000.0, 1.0),
        ),
        workload_forecast=None,
        source="prometheus",
    )
    model_context = ModelContext(
        profile=ModelStructureProfile(
            profile_id="model-a-profile-v1",
            model_id="model-a",
            model_version="1",
            blocks=(
                ModelBlock("block-1", ("layer-1",), 1_000, 100, 200),
                ModelBlock("block-2", ("layer-2",), 1_000, 100, 200),
            ),
        ),
        registry=ModelRegistryContext(
            registry_id="registry-model-a",
            registry_version="registry-v1",
            model_id="model-a",
            approved_model_version="1",
        ),
        source="model-registry",
    )
    return FederatedCoordinationV04Adapter().adapt(
        FederatedCoordinationPlanV04.from_dict(payload),
        participant_context,
        model_context,
    )


def _orchestrator() -> ModelPartitionOrchestrationAgent:
    return ModelPartitionOrchestrationAgent(
        ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json"),
        plan_id_factory=lambda: "partition-plan-fl-test",
    )


def test_fl_strategy_creates_one_full_model_replica_per_participant():
    request = _request()

    plan = _orchestrator().plan_request(request)

    selected = plan.selected_candidate
    assert selected is not None
    assert plan.strategy_id == "federated-full-model-v1"
    assert [partition.layer_names for partition in selected.partitions] == [
        ("layer-1", "layer-2"),
        ("layer-1", "layer-2"),
    ]
    assert [partition.device_id for partition in selected.partitions] == [
        "node-a",
        "node-b",
    ]


def test_fl_strategy_builds_remote_participant_to_aggregator_graph():
    request = _request()

    plan = _orchestrator().plan_request(request)

    selected = plan.selected_candidate
    assert selected is not None
    assert {node.partition_id for node in selected.graph_nodes} == {
        "partition-1",
        "partition-2",
        "aggregation",
    }
    assert [
        (edge.source_partition, edge.target_partition, edge.edge_type)
        for edge in selected.graph_edges
    ] == [("partition-2", "aggregation", "aggregation")]
    assert PartitionPlanValidator().validate(request, plan).valid is True


def test_fl_strategy_rejects_full_model_replica_when_memory_is_insufficient():
    request = _request(memory_available=1_000)

    plan = _orchestrator().plan_request(request)

    assert plan.valid is False
    assert plan.selected_candidate is None
    assert any(
        "memory_capacity_exceeded" in reason
        for candidate in plan.alternative_candidates
        for reason in candidate.rejection_reasons
    )


def test_fl_strategy_is_deterministic_for_identical_context():
    request = _request()
    orchestrator = _orchestrator()

    first = orchestrator.plan_request(request)
    second = orchestrator.plan_request(request)

    assert first.selected_candidate == second.selected_candidate
    assert first.deterministic_signature == second.deterministic_signature

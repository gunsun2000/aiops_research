from __future__ import annotations

from copy import deepcopy

import pytest

from aiops_k8s_agents.federated_coordination_adapter import (
    FederatedCoordinationPlanV04,
    FederatedCoordinationV04Adapter,
    ModelContext,
    ParticipantContext,
)
from aiops_k8s_agents.partition_context import (
    ModelBlock,
    ModelRegistryContext,
    ModelStructureProfile,
)
from aiops_k8s_agents.partition_models import (
    NetworkLink,
    PartitionContractError,
    ResourceDevice,
)


def _training_payload(mode: str = "FL") -> dict:
    return {
        "schema_version": "0.4",
        "task_type": "federated_training",
        "round_plan_id": f"round-plan-{mode.lower()}",
        "job_id": f"{mode.lower()}-training-001",
        "session_id": "session-001",
        "model_ref": {"model_id": "model-a", "version": 1},
        "learning_mode": {"selected": mode, "fallback_order": ["SL"]},
        "coordination_mode": {"selected": "SYNC"},
        "federated_strategy": {
            "name": "FedAWARE" if mode == "FL" else "SplitFed",
            "aggregation_operator": "adaptive_weighted_aggregation",
            "parameter_ref": "default-v1",
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


def _inference_payload() -> dict:
    return {
        "schema_version": "0.4",
        "task_type": "distributed_inference",
        "round_plan_id": "inference-plan-001",
        "inference_plan_id": "inference-plan-001",
        "job_id": "inference-001",
        "session_id": "session-003",
        "model_ref": {"model_id": "model-a", "version": 1},
        "inference_mode": {
            "selected": "PARTITIONED",
            "fallback_order": ["REPLICATED"],
        },
        "candidate_participants": [
            {"client_id": "node-a", "priority": 1},
            {"client_id": "node-b", "priority": 2},
        ],
        "serving_policy": {
            "routing_policy": "LEAST_LOADED",
            "candidate_pool_size": 2,
            "pipeline_parallelism": 2,
            "max_batch_size": 8,
            "max_concurrent_requests": 32,
            "request_timeout_sec": 10,
            "target_latency_ms": 200,
        },
    }


def _participant_context(*, include_link: bool = True) -> ParticipantContext:
    devices = (
        ResourceDevice("node-a", "gpu", 200.0, 8_000, 7_000),
        ResourceDevice("node-b", "gpu", 180.0, 8_000, 7_000),
    )
    links = (
        NetworkLink("node-a", "node-b", 1_000_000.0, 1.0),
        NetworkLink("node-b", "node-a", 1_000_000.0, 1.0),
    )
    return ParticipantContext(
        snapshot_id="prometheus-snapshot-001",
        snapshot_version="prometheus-v1",
        collected_at="2026-08-24T12:00:00Z",
        devices=devices,
        network_links=links if include_link else (),
        workload_forecast=None,
        source="prometheus",
    )


def _model_context() -> ModelContext:
    return ModelContext(
        profile=ModelStructureProfile(
            profile_id="model-a-profile-v1",
            model_id="model-a",
            model_version="1",
            blocks=(
                ModelBlock("block-1", ("layer-1",), 500, 100, 200),
                ModelBlock("block-2", ("layer-2",), 500, 100, 200),
                ModelBlock("block-3", ("layer-3",), 500, 100, 200),
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


@pytest.mark.parametrize(
    ("payload", "plan_type", "execution_mode"),
    [
        (_training_payload("FL"), "training", "federated_learning"),
        (_training_payload("SL"), "training", "split_learning"),
        (_inference_payload(), "inference", "split_inference"),
    ],
)
def test_adapter_maps_supported_v04_modes(payload, plan_type, execution_mode):
    parsed = FederatedCoordinationPlanV04.from_dict(payload)

    request = FederatedCoordinationV04Adapter().adapt(
        parsed,
        _participant_context(),
        _model_context(),
    )

    assert request.envelope.plan_type == plan_type
    assert request.envelope.plan_id == (
        payload.get("inference_plan_id") or payload["round_plan_id"]
    )
    assert request.envelope.approved_by == "FederatedCoordinationAgent"
    assert request.approved_execution_mode is not None
    assert request.approved_execution_mode.name == execution_mode
    assert request.plan.participants == ("node-a", "node-b")
    assert request.context.snapshot_id == "prometheus-snapshot-001"


def test_adapter_preserves_upstream_policy_fields_in_v2_plan():
    payload = _training_payload("FL")

    request = FederatedCoordinationV04Adapter().adapt(
        FederatedCoordinationPlanV04.from_dict(payload),
        _participant_context(),
        _model_context(),
    )

    assert request.plan.aggregation_policy == payload["federated_strategy"]
    assert request.plan.round_policy == payload["participation_policy"]
    assert request.plan.synchronization_policy == payload["coordination_mode"]


def test_parser_rejects_unknown_selected_mode_without_using_fallback():
    payload = _training_payload("UNKNOWN")

    with pytest.raises(PartitionContractError) as error:
        FederatedCoordinationPlanV04.from_dict(payload)

    assert error.value.code == "unsupported_coordination_mode"


def test_adapter_rejects_model_context_that_does_not_match_model_ref():
    context = _model_context()
    mismatched = ModelContext(
        profile=context.profile,
        registry=ModelRegistryContext(
            registry_id=context.registry.registry_id,
            registry_version=context.registry.registry_version,
            model_id="model-b",
            approved_model_version="1",
        ),
        source=context.source,
    )

    with pytest.raises(PartitionContractError) as error:
        FederatedCoordinationV04Adapter().adapt(
            FederatedCoordinationPlanV04.from_dict(_training_payload("FL")),
            _participant_context(),
            mismatched,
        )

    assert error.value.code == "model_context_missing"


def test_adapter_rejects_split_learning_without_bandwidth_evidence():
    with pytest.raises(PartitionContractError) as error:
        FederatedCoordinationV04Adapter().adapt(
            FederatedCoordinationPlanV04.from_dict(_training_payload("SL")),
            _participant_context(include_link=False),
            _model_context(),
        )

    assert error.value.code == "network_evidence_missing"


def test_parser_does_not_mutate_original_payload():
    payload = _inference_payload()
    original = deepcopy(payload)

    FederatedCoordinationPlanV04.from_dict(payload)

    assert payload == original

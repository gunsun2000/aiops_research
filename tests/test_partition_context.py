from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_context import PartitionSystemContext
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_models import PartitionContractError


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def context_payload() -> dict:
    return {
        "snapshot_id": "snapshot-inference-001",
        "snapshot_version": "2026-08-20.1",
        "collected_at": "2026-08-20T08:55:00Z",
        "model_structure_profile": {
            "profile_id": "transformer-profile-v3",
            "model_id": "transformer-service",
            "model_version": "transformer-v3",
            "blocks": [
                {
                    "block_id": "embedding",
                    "layer_names": ["embedding"],
                    "parameter_bytes": 12_000_000,
                    "activation_bytes": 4_000_000,
                    "working_memory_bytes": 8_000_000,
                },
                {
                    "block_id": "encoder-01",
                    "layer_names": ["encoder-01", "encoder-02"],
                    "parameter_bytes": 32_000_000,
                    "activation_bytes": 3_000_000,
                    "working_memory_bytes": 20_000_000,
                },
            ],
        },
        "model_registry_context": {
            "registry_id": "model-registry-001",
            "registry_version": "2026-08-20.1",
            "model_id": "transformer-service",
            "approved_model_version": "transformer-v3",
        },
        "devices": [
            {
                "device_id": "edge-cpu-01",
                "device_type": "cpu",
                "compute_units_per_second": 1_000.0,
                "memory_capacity_bytes": 268_435_456,
                "memory_available_bytes": 209_715_200,
            },
            {
                "device_id": "gpu-worker-01",
                "device_type": "gpu",
                "compute_units_per_second": 2_000.0,
                "memory_capacity_bytes": 536_870_912,
                "memory_available_bytes": 471_859_200,
            },
        ],
        "network_links": [
            {
                "source_device": "edge-cpu-01",
                "target_device": "gpu-worker-01",
                "bandwidth_bytes_per_second": 10_000_000.0,
                "latency_ms": 2.0,
            }
        ],
        "workload_forecast": {
            "forecast_id": "forecast-inference-001",
            "horizon_seconds": 300,
            "expected_request_rate": 25.0,
            "expected_batch_size": 4,
            "expected_sequence_length": 512,
            "uncertainty": 0.15,
            "source": "capacity-planning",
        },
    }


@pytest.fixture
def inference_payload(context_payload) -> dict:
    return {
        "coordination_plan": {
            "plan_type": "inference",
            "plan_id": "coordination-inference-001",
            "job_id": "job-inference-001",
            "approved": True,
            "approved_by": "FederatedCoordinationAgent",
            "approval_ref": "approval-inference-001",
            "approved_at": "2026-08-20T09:00:00Z",
            "schema_version": "model-partition-coordination-v2",
            "payload": {
                "model_id": "transformer-service",
                "approved_model_version": "transformer-v3",
                "service_objective": "low-latency text generation",
                "latency_slo_ms": 150.0,
                "minimum_throughput_rps": 25.0,
                "availability_target": 0.99,
                "traffic_policy": {"routing": "weighted"},
                "concurrency_policy": {"max_requests": 16},
                "participants": ["edge-cpu-01", "gpu-worker-01"],
                "resource_budget": {"max_devices": 2},
                "constraints": {
                    "max_end_to_end_latency_ms": 150.0,
                    "max_transfer_bytes": 5_000_000,
                    "minimum_memory_headroom_ratio": 0.1,
                },
            },
        },
        "system_context": context_payload,
    }


def test_context_hash_is_stable_for_key_order(context_payload):
    first = PartitionSystemContext.from_dict(context_payload)
    reordered = json.loads(json.dumps(context_payload, sort_keys=True))
    second = PartitionSystemContext.from_dict(reordered)

    assert first.deterministic_hash() == second.deterministic_hash()


def test_context_is_immutable_after_deserialization(context_payload):
    context = PartitionSystemContext.from_dict(context_payload)

    with pytest.raises(FrozenInstanceError):
        context.snapshot_id = "snapshot-mutated"


def test_model_version_mismatch_fails_closed(inference_payload):
    inference_payload["system_context"]["model_registry_context"][
        "approved_model_version"
    ] = "transformer-v2"

    with pytest.raises(PartitionContractError) as error:
        PartitionPlanningRequest.from_dict(inference_payload)

    assert error.value.code == "model_version_mismatch"


@pytest.mark.parametrize(
    ("path", "plan_type"),
    [
        ("config/examples/model_partition_inference_v2.json", "inference"),
        ("config/examples/model_partition_training_v2.json", "training"),
    ],
)
def test_v2_examples_parse_as_versioned_requests(path, plan_type):
    payload = json.loads((ROOT / path).read_text(encoding="utf-8"))

    request = PartitionPlanningRequest.from_dict(deepcopy(payload))

    assert request.envelope.plan_type == plan_type
    assert len(request.context.deterministic_hash()) == 64

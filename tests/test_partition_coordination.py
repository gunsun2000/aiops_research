from __future__ import annotations

from copy import deepcopy

import pytest

from aiops_k8s_agents.partition_coordination import (
    InferenceCoordinationPlan,
    PartitionPlanningRequest,
    TrainingCoordinationPlan,
)
from aiops_k8s_agents.partition_models import PartitionContractError


@pytest.fixture
def inference_payload() -> dict:
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
        "system_context": {
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
                    }
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
        },
    }


def test_v2_request_requires_approved_plan_provenance(inference_payload):
    inference_payload["coordination_plan"]["approved_by"] = ""

    with pytest.raises(PartitionContractError) as error:
        PartitionPlanningRequest.from_dict(inference_payload)

    assert error.value.code == "approval_provenance_required"


def test_v2_request_routes_inference_payload(inference_payload):
    request = PartitionPlanningRequest.from_dict(inference_payload)

    assert request.envelope.plan_type == "inference"
    assert isinstance(request.plan, InferenceCoordinationPlan)
    assert request.plan.approved_model_version == "transformer-v3"


def test_v2_request_routes_training_pipeline_parallel_payload(inference_payload):
    payload = deepcopy(inference_payload)
    payload["coordination_plan"]["plan_type"] = "training"
    payload["coordination_plan"]["payload"] = {
        "model_id": "transformer-training",
        "approved_model_version": "transformer-v3",
        "coordination_mode": "pipeline_parallel",
        "participants": ["gpu-worker-01", "gpu-worker-02"],
        "round_policy": {"rounds": 8},
        "aggregation_policy": {"name": "fedavg"},
        "synchronization_policy": {"name": "synchronous"},
        "training_objective": "minimize step time",
        "resource_budget": {"max_devices": 2},
        "constraints": {
            "max_end_to_end_latency_ms": 1_000.0,
            "max_transfer_bytes": 20_000_000,
            "minimum_memory_headroom_ratio": 0.1,
        },
    }
    payload["system_context"]["model_structure_profile"]["profile_id"] = (
        "transformer-training-profile-v3"
    )
    payload["system_context"]["model_structure_profile"]["model_id"] = (
        "transformer-training"
    )
    payload["system_context"]["model_registry_context"]["model_id"] = (
        "transformer-training"
    )
    payload["system_context"]["devices"] = [
        {
            "device_id": "gpu-worker-01",
            "device_type": "gpu",
            "compute_units_per_second": 2_000.0,
            "memory_capacity_bytes": 536_870_912,
            "memory_available_bytes": 471_859_200,
        },
        {
            "device_id": "gpu-worker-02",
            "device_type": "gpu",
            "compute_units_per_second": 2_200.0,
            "memory_capacity_bytes": 536_870_912,
            "memory_available_bytes": 471_859_200,
        },
    ]
    payload["system_context"]["network_links"] = [
        {
            "source_device": "gpu-worker-01",
            "target_device": "gpu-worker-02",
            "bandwidth_bytes_per_second": 40_000_000.0,
            "latency_ms": 1.0,
        }
    ]

    request = PartitionPlanningRequest.from_dict(payload)

    assert isinstance(request.plan, TrainingCoordinationPlan)
    assert request.plan.coordination_mode == "pipeline_parallel"

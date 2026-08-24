from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiops_k8s_agents.federated_coordination_adapter import (
    MappingModelContextProvider,
    MappingParticipantContextProvider,
    ModelContext,
    ParticipantContext,
)
from aiops_k8s_agents.partition_context import (
    ModelBlock,
    ModelRegistryContext,
    ModelStructureProfile,
)
from aiops_k8s_agents.partition_models import NetworkLink, ResourceDevice
from aiops_k8s_agents.partition_service import run_federated_coordination_planning


ROOT = Path(__file__).resolve().parents[1]


def _payload(mode: str) -> dict:
    common = {
        "schema_version": "0.4",
        "job_id": f"job-{mode.lower()}",
        "session_id": "session-001",
        "model_ref": {"model_id": "model-a", "version": 1},
        "candidate_participants": [
            {"client_id": "node-a", "priority": 1},
            {"client_id": "node-b", "priority": 2},
        ],
    }
    if mode in {"FL", "SL"}:
        return {
            **common,
            "task_type": "federated_training",
            "round_plan_id": f"round-plan-{mode.lower()}",
            "learning_mode": {"selected": mode, "fallback_order": []},
            "coordination_mode": {"selected": "SYNC"},
            "federated_strategy": {
                "name": "FedAWARE" if mode == "FL" else "SplitFed",
                "aggregation_operator": "adaptive_weighted_aggregation",
                "parameter_ref": "default-v1",
            },
            "participation_policy": {
                "type": "SYNC",
                "candidate_pool_size": 2,
                "target_active": 2,
                "minimum_successful_participants": 1,
            },
        }
    return {
        **common,
        "task_type": "distributed_inference",
        "round_plan_id": "inference-plan-partitioned",
        "inference_plan_id": "inference-plan-partitioned",
        "inference_mode": {"selected": "PARTITIONED", "fallback_order": []},
        "serving_policy": {
            "routing_policy": "LEAST_LOADED",
            "pipeline_parallelism": 2,
            "max_batch_size": 8,
            "max_concurrent_requests": 32,
            "request_timeout_sec": 10,
            "target_latency_ms": 200,
        },
    }


def _providers(*, include_model: bool = True):
    participant_provider = MappingParticipantContextProvider(
        ParticipantContext(
            snapshot_id="prometheus-snapshot-service",
            snapshot_version="prometheus-v1",
            collected_at="2026-08-24T12:00:00Z",
            devices=(
                ResourceDevice("node-a", "gpu", 200.0, 20_000, 18_000),
                ResourceDevice("node-b", "gpu", 180.0, 20_000, 18_000),
            ),
            network_links=(
                NetworkLink("node-a", "node-b", 1_000_000.0, 1.0),
                NetworkLink("node-b", "node-a", 1_000_000.0, 1.0),
            ),
            workload_forecast=None,
            source="prometheus",
        )
    )
    model_context = ModelContext(
        profile=ModelStructureProfile(
            profile_id="model-a-profile-v1",
            model_id="model-a",
            model_version="1",
            blocks=tuple(
                ModelBlock(f"block-{index}", (f"layer-{index}",), 500, 100, 200)
                for index in range(1, 5)
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
    model_provider = MappingModelContextProvider(
        {("model-a", "1"): model_context} if include_model else {}
    )
    return participant_provider, model_provider


@pytest.mark.parametrize(
    ("mode", "strategy_id"),
    [
        ("FL", "federated-full-model-v1"),
        ("SL", "training-partition-v1"),
        ("PARTITIONED", "inference-partition-v1"),
    ],
)
def test_service_runs_v04_plan_through_shared_pipeline(tmp_path, mode, strategy_id):
    participant_provider, model_provider = _providers()

    report = run_federated_coordination_planning(
        _payload(mode),
        participant_provider=participant_provider,
        model_provider=model_provider,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
        plan_id_factory=lambda: f"plan-{mode.lower()}",
    )

    assert report["status"] == "planned"
    assert report["plan"]["strategy_id"] == strategy_id
    assert report["validation"]["valid"] is True
    assert report["context_enrichment"]["status"] == "complete"
    assert report["context_enrichment"]["participant_source"] == "prometheus"
    assert report["context_enrichment"]["model_source"] == "model-registry"


def test_service_returns_blocked_result_when_model_context_is_missing(tmp_path):
    participant_provider, model_provider = _providers(include_model=False)

    report = run_federated_coordination_planning(
        _payload("FL"),
        participant_provider=participant_provider,
        model_provider=model_provider,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
    )

    assert report["status"] == "blocked"
    assert report["error"]["code"] == "model_context_missing"
    assert report["context_enrichment"]["status"] == "blocked"


def test_service_persists_original_upstream_payload(tmp_path):
    participant_provider, model_provider = _providers()
    payload = _payload("SL")

    report = run_federated_coordination_planning(
        payload,
        participant_provider=participant_provider,
        model_provider=model_provider,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
        plan_id_factory=lambda: "plan-persisted-upstream",
    )
    persisted = json.loads(Path(report["artifact_path"]).read_text(encoding="utf-8"))

    assert persisted["upstream_coordination"] == payload
    assert persisted["context_enrichment"]["snapshot_id"] == (
        "prometheus-snapshot-service"
    )

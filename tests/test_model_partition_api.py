import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aiops_k8s_agents import control_plane_web
from aiops_k8s_agents import partition_ranker_repository
from aiops_k8s_agents.control_plane_web import create_app
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
from aiops_k8s_agents.partition_features import FEATURE_ORDER
from aiops_k8s_agents.partition_models import NetworkLink, ResourceDevice
from aiops_k8s_agents.partition_ranker_repository import (
    VALIDATION_METRIC_KEYS,
    PartitionRankerModelArtifact,
    PartitionRankerRepository,
)


def _example_payload() -> dict:
    return json.loads(
        Path("config/examples/model_partition_job.json").read_text(encoding="utf-8")
    )


def _inference_payload() -> dict:
    payload = json.loads(
        Path(
            "config/examples/model_partition_inference_v2.json"
        ).read_text(encoding="utf-8")
    )
    payload["coordination_plan"]["payload"]["latency_slo_ms"] = 500.0
    payload["coordination_plan"]["payload"]["constraints"][
        "max_end_to_end_latency_ms"
    ] = 500.0
    return payload


def _federated_coordination_payload() -> dict:
    return {
        "schema_version": "0.4",
        "task_type": "federated_training",
        "round_plan_id": "round-plan-api-fl",
        "job_id": "fl-training-api",
        "session_id": "session-api",
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


def _federated_context_providers():
    participant_provider = MappingParticipantContextProvider(
        ParticipantContext(
            snapshot_id="prometheus-snapshot-api",
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
    model_provider = MappingModelContextProvider(
        {
            ("model-a", "1"): ModelContext(
                profile=ModelStructureProfile(
                    profile_id="model-a-profile-api",
                    model_id="model-a",
                    model_version="1",
                    blocks=tuple(
                        ModelBlock(
                            f"block-{index}",
                            (f"layer-{index}",),
                            500,
                            100,
                            200,
                        )
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
        }
    )
    return participant_provider, model_provider


def _write_federated_context_file(tmp_path: Path) -> Path:
    path = tmp_path / "federated-context.json"
    path.write_text(
        json.dumps(
            {
                "participant_context": {
                    "snapshot_id": "prometheus-snapshot-file",
                    "snapshot_version": "prometheus-v1",
                    "collected_at": "2026-08-24T12:00:00Z",
                    "source": "prometheus",
                    "devices": [
                        {
                            "device_id": "node-a",
                            "device_type": "gpu",
                            "compute_units_per_second": 200.0,
                            "memory_capacity_bytes": 20000,
                            "memory_available_bytes": 18000,
                        },
                        {
                            "device_id": "node-b",
                            "device_type": "gpu",
                            "compute_units_per_second": 180.0,
                            "memory_capacity_bytes": 20000,
                            "memory_available_bytes": 18000,
                        },
                    ],
                    "network_links": [
                        {
                            "source_device": "node-a",
                            "target_device": "node-b",
                            "bandwidth_bytes_per_second": 1000000.0,
                            "latency_ms": 1.0,
                        },
                        {
                            "source_device": "node-b",
                            "target_device": "node-a",
                            "bandwidth_bytes_per_second": 1000000.0,
                            "latency_ms": 1.0,
                        },
                    ],
                },
                "model_contexts": [
                    {
                        "model_id": "model-a",
                        "model_version": "1",
                        "source": "model-registry",
                        "profile": {
                            "profile_id": "model-a-profile-file",
                            "model_id": "model-a",
                            "model_version": "1",
                            "blocks": [
                                {
                                    "block_id": f"block-{index}",
                                    "layer_names": [f"layer-{index}"],
                                    "parameter_bytes": 500,
                                    "activation_bytes": 100,
                                    "working_memory_bytes": 200,
                                }
                                for index in range(1, 5)
                            ],
                        },
                        "registry": {
                            "registry_id": "registry-model-a",
                            "registry_version": "registry-v1",
                            "model_id": "model-a",
                            "approved_model_version": "1",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _latency_feedback(report: dict) -> dict:
    return {
        "signal": "latency_slo_violation",
        "source": "runtime-monitor",
        "reason": "observed latency exceeded the approved SLO",
        "received_at": "2026-08-20T00:00:00+00:00",
        "plan_id": report["plan"]["plan_id"],
        "plan_version": report["plan"]["plan_version"],
    }


def _unexpected_partition_service(*_args, **_kwargs):
    raise RuntimeError("internal-token-must-not-be-exposed")


def _custom_policy_path(tmp_path: Path) -> Path:
    policy = json.loads(
        Path("config/model_partition_policy.json").read_text(encoding="utf-8")
    )
    policy["version"] = "partition-policy-api-test"
    policy["confidence"]["base"] = 0.61
    policy["strategy_policies"]["inference-partition-v1"]["objectives"] = {
        "latency": 0.1,
        "memory_pressure": 0.7,
        "communication": 0.2,
    }
    path = tmp_path / "custom-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def _ranker_registry(tmp_path: Path) -> Path:
    registry = tmp_path / "ranker-registry"
    repository = PartitionRankerRepository(registry)
    for model_version, sample_count in (
        ("partition-ridge-observed-v1", 30),
        ("undertrained-v1", 29),
    ):
        artifact = PartitionRankerModelArtifact(
            schema_version="partition-ranker-model-v2",
            model_type="ridge_reward_regressor",
            model_version=model_version,
            feature_schema_version="partition-feature-v1",
            trained_at="2026-08-21T00:00:00Z",
            training_dataset_hash="a" * 64,
            training_scope="observed",
            sample_count=sample_count,
            group_count=5,
            feature_order=FEATURE_ORDER,
            feature_mean=tuple(0.0 for _ in FEATURE_ORDER),
            feature_scale=tuple(1.0 for _ in FEATURE_ORDER),
            coefficients=tuple(0.0 for _ in FEATURE_ORDER),
            intercept=0.0,
            training_feature_ranges={
                name: (0.0, 10_000_000_000.0) for name in FEATURE_ORDER
            },
            validation_metrics={
                **{key: 0.0 for key in VALIDATION_METRIC_KEYS},
                "holdout_mae": 0.1,
                "mae": 0.1,
                "rmse": 0.1,
                "spearman_correlation": 0.8,
            },
            confidence_policy={"base_confidence": 0.95},
            training_provenance={
                "seed": 17,
                "ridge_alpha": 1.0,
                "holdout_test_fraction": 0.2,
                "eligibility_thresholds": {
                    "minimum_observed_samples": 30,
                    "minimum_independent_groups": 5,
                    "maximum_holdout_mae": 0.25,
                    "minimum_spearman_correlation": 0.3,
                    "minimum_selection_confidence": 0.7,
                    "maximum_ood_feature_ratio": 0.2,
                },
                "training_lineage_group_hashes": tuple(
                    f"{index:x}" * 64 for index in range(1, 6)
                ),
            },
            artifact_hash="",
        ).with_computed_hash()
        repository.save(artifact)
    return registry


def _tamper_ranker_artifact(registry: Path, model_version: str) -> None:
    artifact_path = registry / model_version / "model.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["intercept"] = 0.25
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")


def test_plan_api_accepts_shadow_mode_with_registered_model(tmp_path):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=_ranker_registry(tmp_path),
        )
    )

    response = client.post(
        "/api/model-partition/plans",
        json={
            "request": _inference_payload(),
            "selection_mode": "shadow",
            "ranker_model_version": "partition-ridge-observed-v1",
        },
    )

    assert response.status_code == 200
    assert response.json()["plan"]["selection"]["mode"] == "shadow"


def test_ranker_status_explains_guarded_ineligibility(tmp_path):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=_ranker_registry(tmp_path),
        )
    )

    response = client.get("/api/model-partition/rankers/undertrained-v1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["guarded_eligible"] is False
    assert payload["guard_failures"] == ["insufficient_observed_samples"]
    assert payload["sample_count"] == 29
    assert payload["training_scope"] == "observed"


def test_ranker_status_list_exposes_registered_model_metadata(tmp_path):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=_ranker_registry(tmp_path),
        )
    )

    response = client.get("/api/model-partition/rankers")

    assert response.status_code == 200
    models = response.json()["models"]
    assert [model["model_version"] for model in models] == [
        "partition-ridge-observed-v1",
        "undertrained-v1",
    ]
    assert models[0]["feature_schema_version"] == "partition-feature-v1"
    assert models[0]["guarded_eligible"] is True
    assert models[0]["guard_failures"] == []


def test_ranker_status_surfaces_corrupt_registered_artifact_without_path(tmp_path):
    registry = _ranker_registry(tmp_path)
    _tamper_ranker_artifact(registry, "partition-ridge-observed-v1")
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=registry,
        )
    )

    detail = client.get("/api/model-partition/rankers/partition-ridge-observed-v1")
    collection = client.get("/api/model-partition/rankers")

    assert detail.status_code == 422
    assert detail.json() == {
        "error_code": "invalid_model_artifact",
        "integrity_reason": "artifact_hash_mismatch",
        "message": "registered ranker artifact failed integrity validation",
        "model_version": "partition-ridge-observed-v1",
    }
    assert collection.status_code == 200
    assert [model["model_version"] for model in collection.json()["models"]] == [
        "undertrained-v1"
    ]
    assert collection.json()["integrity_errors"] == [
        {
            "error_code": "invalid_model_artifact",
            "integrity_reason": "artifact_hash_mismatch",
            "message": "registered ranker artifact failed integrity validation",
            "model_version": "partition-ridge-observed-v1",
        }
    ]


def test_ranker_collection_rejects_reparse_registry_root_before_listing(
    tmp_path, monkeypatch
):
    registry = tmp_path / "ranker-registry"
    registry.mkdir()
    external_model_name = "external-only-model-v1"
    (registry / external_model_name).mkdir()

    monkeypatch.setattr(
        partition_ranker_repository,
        "_is_link",
        lambda path: Path(path).absolute() == registry.absolute(),
    )
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=registry,
        )
    )

    response = client.get("/api/model-partition/rankers")

    assert response.status_code == 422
    assert response.json() == {
        "error_code": "invalid_model_artifact",
        "integrity_reason": "artifact_validation_failed",
        "message": "registered ranker artifact failed integrity validation",
    }
    assert external_model_name not in response.text


@pytest.mark.parametrize("path_like_version", ("../../model.json", r"C:\\model.json"))
def test_ranker_api_rejects_path_like_model_versions(tmp_path, path_like_version):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=_ranker_registry(tmp_path),
        )
    )

    response = client.post(
        "/api/model-partition/plans",
        json={
            "request": _inference_payload(),
            "selection_mode": "shadow",
            "ranker_model_version": path_like_version,
        },
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_model_version"


def test_ranker_api_returns_not_found_for_unknown_model_version(tmp_path):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=_ranker_registry(tmp_path),
        )
    )

    response = client.get("/api/model-partition/rankers/not-registered-v1")

    assert response.status_code == 404
    assert response.json()["error_code"] == "model_not_found"


@pytest.mark.parametrize(
    "encoded_version",
    (
        "..%2F..%2Fmodel.json",
        "%2E%2E%2F%2E%2E%2Fmodel.json",
        "C:%5Cmodel.json",
    ),
)
def test_ranker_detail_rejects_encoded_path_like_model_versions(
    tmp_path, encoded_version
):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=_ranker_registry(tmp_path),
        )
    )

    response = client.get(f"/api/model-partition/rankers/{encoded_version}")

    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_model_version"


def test_ranker_detail_accepts_valid_version_token(tmp_path):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=_ranker_registry(tmp_path),
        )
    )

    response = client.get(
        "/api/model-partition/rankers/partition-ridge-observed-v1"
    )

    assert response.status_code == 200
    assert response.json()["model_version"] == "partition-ridge-observed-v1"


def test_plan_api_keeps_legacy_request_deterministic_when_rankers_exist(tmp_path):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=_ranker_registry(tmp_path),
        )
    )

    response = client.post(
        "/api/model-partition/plans",
        json={
            "round_plan": _example_payload(),
            "selection_mode": "learned_guarded",
            "ranker_model_version": "partition-ridge-observed-v1",
            "legacy_extension": "preserved-compatible-extra",
        },
    )

    assert response.status_code == 200
    assert response.json()["plan"]["selection"]["mode"] == "deterministic"


@pytest.mark.parametrize(
    "reserved_field, value",
    (
        ("artifact_signing_key", "untrusted-http-key"),
        ("artifact_signing_key_file", "../../untrusted.key"),
        ("ranker_registry_root", "../../untrusted-registry"),
    ),
)
def test_plan_api_rejects_http_server_owned_fields(tmp_path, reserved_field, value):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.post(
        "/api/model-partition/plans",
        json={"request": _inference_payload(), reserved_field: value},
    )

    assert response.status_code == 422


def test_plan_api_uses_only_server_owned_artifact_hmac_configuration(tmp_path):
    captured: dict[str, object] = {}

    def service(*_args, **kwargs):
        captured.update(kwargs)
        return {"status": "planned"}

    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            model_partition_service=service,
            partition_artifact_signing_key="trusted-server-key",
        )
    )

    response = client.post(
        "/api/model-partition/plans",
        json={"request": _inference_payload()},
    )

    assert response.status_code == 200
    assert captured["artifact_signing_key"] == "trusted-server-key"
    assert captured["artifact_signing_key_file"] is None


def test_feedback_api_uses_server_owned_ranker_registry_root(tmp_path, monkeypatch):
    captured: dict[str, object] = {}
    registry = _ranker_registry(tmp_path)

    def feedback_service(*_args, **kwargs):
        captured.update(kwargs)
        return {"status": "feedback_recorded"}

    monkeypatch.setattr(control_plane_web, "run_partition_feedback", feedback_service)
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            ranker_registry_root=registry,
        )
    )

    response = client.post(
        "/api/model-partition/plans/plan-001/feedback",
        json={"signal": "latency_slo_violation"},
    )

    assert response.status_code == 200
    assert captured["ranker_registry_root"] == registry.resolve()


def test_model_partition_examples_expose_approved_upstream_contract(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.get("/api/model-partition/examples")

    assert response.status_code == 200
    example = response.json()["examples"][0]
    assert example["round_plan"]["execution_mode"]["approved"] is True
    assert example["round_plan"]["execution_mode"]["approved_by"]
    assert example["scope"]["selects_execution_mode"] is False


def test_model_partition_examples_expose_v2_inference_and_training_contracts(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.get("/api/model-partition/examples")

    assert response.status_code == 200
    v2_examples = {
        item["request"]["coordination_plan"]["plan_type"]: item["request"]
        for item in response.json()["examples"]
        if "request" in item
    }
    assert set(v2_examples) == {"inference", "training"}
    assert v2_examples["inference"]["coordination_plan"]["approved_at"]
    assert v2_examples["inference"]["coordination_plan"]["payload"][
        "traffic_policy"
    ] == {"routing": "weighted"}
    assert v2_examples["inference"]["coordination_plan"]["payload"][
        "concurrency_policy"
    ] == {"max_requests": 16}
    assert v2_examples["training"]["approved_execution_mode"]["name"] == (
        "pipeline_parallel"
    )


def test_model_partition_examples_expose_federated_coordination_v04_inputs(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.get("/api/model-partition/examples")

    assert response.status_code == 200
    coordination_examples = {
        item["coordination_plan"]["learning_mode"]["selected"]
        if "learning_mode" in item["coordination_plan"]
        else item["coordination_plan"]["inference_mode"]["selected"]
        for item in response.json()["examples"]
        if "coordination_plan" in item
    }
    assert coordination_examples == {"FL", "SL", "PARTITIONED"}


def test_model_partition_plan_api_runs_shared_validated_service(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.post(
        "/api/model-partition/plans",
        json={"round_plan": _example_payload()},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "planned"
    assert report["plan"]["selected_candidate"]["split_points"] == [3]
    assert report["validation"]["valid"] is True
    assert report["evaluation"]["evidence_level"] == "predicted"
    assert report["evaluation"]["estimated"] is True
    assert Path(report["artifact_path"]).is_file()


def test_federated_coordination_plan_api_accepts_v04_input(tmp_path):
    participant_provider, model_provider = _federated_context_providers()
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            federated_participant_provider=participant_provider,
            federated_model_provider=model_provider,
        )
    )

    response = client.post(
        "/api/model-partition/coordination-plan",
        json=_federated_coordination_payload(),
    )

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "planned"
    assert report["plan"]["strategy_id"] == "federated-full-model-v1"
    assert report["upstream_coordination"]["schema_version"] == "0.4"
    assert report["context_enrichment"]["participant_source"] == "prometheus"


def test_federated_coordination_plan_api_fails_closed_without_context_providers(
    tmp_path,
):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.post(
        "/api/model-partition/coordination-plan",
        json=_federated_coordination_payload(),
    )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "context_provider_unavailable",
        "message": (
            "participant and model context providers must be configured before "
            "federated coordination plans can be processed"
        ),
    }


def test_federated_coordination_plan_api_loads_context_snapshot_file(tmp_path):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            federated_context_path=_write_federated_context_file(tmp_path),
        )
    )

    response = client.post(
        "/api/model-partition/coordination-plan",
        json=_federated_coordination_payload(),
    )

    assert response.status_code == 200
    assert response.json()["context_enrichment"] == {
        **response.json()["context_enrichment"],
        "status": "complete",
        "participant_source": "prometheus",
        "model_source": "model-registry",
        "snapshot_id": "prometheus-snapshot-file",
    }


def test_legacy_model_partition_invalid_round_plan_preserves_422_detail(tmp_path):
    payload = _example_payload()
    payload["execution_mode"]["approved"] = False
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.post(
        "/api/model-partition/plans",
        json={"round_plan": payload},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "approved_mode_required",
        "message": "execution mode must be approved by the upstream coordinator",
    }


def test_model_partition_plan_api_supports_bounded_replanning(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )
    initial = client.post(
        "/api/model-partition/plans",
        json={"round_plan": _example_payload()},
    ).json()

    response = client.post(
        "/api/model-partition/plans",
        json={
            "round_plan": _example_payload(),
            "previous_plan": initial["plan"],
            "failure": {
                "signal": "latency_slo_violation",
                "details": "runtime latency exceeded the SLO",
            },
            "replan_attempt": 1,
        },
    )

    assert response.status_code == 200
    replanned = response.json()
    assert replanned["replanning"]["attempt"] == 1
    assert replanned["plan"]["selected_candidate"]["split_points"] != [3]


def test_v2_plan_api_returns_versioned_handoff_and_persists_it(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.post(
        "/api/model-partition/plans",
        json={"request": _inference_payload()},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "planned"
    assert report["plan"]["plan_version"] == 1
    assert report["scheduling_handoff"] == {
        **report["scheduling_handoff"],
        "partition_plan_id": report["plan"]["plan_id"],
        "partition_plan_version": 1,
        "status": "ready",
        "scheduler_ref": None,
    }

    stored = client.get(f"/api/model-partition/plans/{report['plan']['plan_id']}")

    assert stored.status_code == 200
    assert stored.json()["plan"] == report["plan"]


def test_v2_plan_api_exposes_strategy_catalog_from_the_policy(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.get("/api/model-partition/strategies")

    assert response.status_code == 200
    assert {
        (strategy["plan_type"], strategy["strategy_id"])
        for strategy in response.json()["strategies"]
    } >= {
        ("inference", "inference-partition-v1"),
        ("training", "training-partition-v1"),
    }


def test_strategy_catalog_exposes_server_owned_strategy_constraints(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    response = client.get("/api/model-partition/strategies")

    assert response.status_code == 200
    strategies = {
        strategy["strategy_id"]: strategy for strategy in response.json()["strategies"]
    }
    inference = strategies["inference-partition-v1"]
    training = strategies["training-partition-v1"]
    assert inference["objective_weights"] == {
        "latency": 0.5,
        "memory_pressure": 0.3,
        "communication": 0.2,
    }
    assert inference["allowed_split_boundary_rule"] == "interior_layer_boundaries"
    assert inference["forbidden_split_boundaries"] == ["first_boundary", "last_boundary"]
    assert inference["graph_requirements"] == [
        "forward_only_dag",
        "adjacent_partition_edges_only",
    ]
    assert inference["memory_rules"] == [
        "per_partition_parameter_bytes",
        "per_partition_working_memory_bytes",
        "per_partition_peak_activation_bytes",
    ]
    assert training["forbidden_split_boundaries"] == [
        "first_boundary",
        2,
        "last_boundary",
    ]
    assert "checkpoint_boundary_memory" in training["memory_rules"]


def test_feedback_api_returns_replanned_version_and_history(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )
    initial = client.post(
        "/api/model-partition/plans",
        json={"request": _inference_payload()},
    ).json()
    plan_id = initial["plan"]["plan_id"]

    response = client.post(
        f"/api/model-partition/plans/{plan_id}/feedback",
        json=_latency_feedback(initial),
    )

    assert response.status_code == 200
    report = response.json()
    assert report["plan"]["plan_version"] == 2
    assert report["plan"]["parent_plan_id"] == plan_id
    assert set(report["evaluation"]["components"]) == set(
        initial["evaluation"]["components"]
    )
    assert set(report["evaluation"]["metrics"]) == set(initial["evaluation"]["metrics"])
    assert report["evaluation"]["metrics"]["throughput_capacity_evidence"] == "predicted"
    assert report["evaluation"]["metrics"]["availability_evidence"] == (
        "predicted_snapshot_feasibility"
    )

    history = client.get(f"/api/model-partition/plans/{report['plan']['plan_id']}/history")

    assert history.status_code == 200
    assert [item["plan"]["plan_version"] for item in history.json()["plans"]] == [
        2,
        1,
    ]


def test_v2_api_returns_stable_contract_errors(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )
    invalid = _inference_payload()
    invalid["coordination_plan"]["approved"] = False

    invalid_response = client.post(
        "/api/model-partition/plans",
        json={"request": invalid},
    )
    missing_response = client.get("/api/model-partition/plans/missing-plan")

    assert invalid_response.status_code == 400
    assert invalid_response.json() == {
        "error_code": "approved_plan_required",
        "message": "coordination plan must be approved",
    }
    assert missing_response.status_code == 404
    assert missing_response.json()["error_code"] == "plan_not_found"


def test_feedback_version_conflict_maps_to_stable_409(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )
    initial = client.post(
        "/api/model-partition/plans",
        json={"request": _inference_payload()},
    ).json()
    feedback = _latency_feedback(initial)
    feedback["plan_version"] = 2

    response = client.post(
        f"/api/model-partition/plans/{initial['plan']['plan_id']}/feedback",
        json=feedback,
    )

    assert response.status_code == 409
    assert response.json() == {
        "error_code": "feedback_plan_mismatch",
        "message": "feedback must identify the persisted plan version being replanned",
    }


def test_v2_api_does_not_expose_unexpected_exception_details(tmp_path):
    client = TestClient(
        create_app(
            model_partition_artifact_root=tmp_path / "artifacts",
            model_partition_service=_unexpected_partition_service,
        )
    )

    response = client.post(
        "/api/model-partition/plans",
        json={"request": _inference_payload()},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "internal_error",
        "message": "model partition request could not be completed",
    }


def test_empty_v2_and_legacy_requests_use_their_respective_error_contracts(tmp_path):
    client = TestClient(
        create_app(model_partition_artifact_root=tmp_path / "artifacts")
    )

    empty_v2 = client.post("/api/model-partition/plans", json={"request": {}})
    empty_legacy = client.post(
        "/api/model-partition/plans", json={"round_plan": {}}
    )

    assert empty_v2.status_code == 400
    assert empty_v2.json() == {
        "error_code": "invalid_contract",
        "message": "coordination_plan must be an object",
    }
    assert empty_legacy.status_code == 422
    assert empty_legacy.json() == {
        "detail": {"code": "invalid_contract", "message": "layers must be an array"}
    }


def test_v2_api_threads_custom_policy_to_strategies_plans_artifacts_and_feedback(
    tmp_path,
):
    policy_path = _custom_policy_path(tmp_path)
    client = TestClient(
        create_app(
            model_partition_policy_path=policy_path,
            model_partition_artifact_root=tmp_path / "artifacts",
        )
    )

    strategies = client.get("/api/model-partition/strategies")
    initial = client.post(
        "/api/model-partition/plans",
        json={"request": _inference_payload()},
    ).json()
    feedback = client.post(
        f"/api/model-partition/plans/{initial['plan']['plan_id']}/feedback",
        json=_latency_feedback(initial),
    ).json()
    intent = json.loads(
        (
            Path(initial["artifact_path"]).parent
            / "versions"
            / "1"
            / "partition_intent.json"
        ).read_text(encoding="utf-8")
    )

    assert strategies.status_code == 200
    assert {
        strategy["policy_version"] for strategy in strategies.json()["strategies"]
    } == {"partition-policy-api-test"}
    assert initial["plan"]["strategy_version"] == (
        "inference-partition-v1:partition-policy-api-test"
    )
    assert initial["plan"]["confidence"] == 0.61
    assert initial["evaluation"]["policy_version"] == "partition-policy-api-test"
    assert intent["strategy_version"] == "inference-partition-v1:partition-policy-api-test"
    assert feedback["plan"]["strategy_version"] == initial["plan"]["strategy_version"]
    assert feedback["evaluation"]["policy_version"] == "partition-policy-api-test"


def test_strategy_catalog_uses_stable_errors_for_bad_and_unexpected_policy_reads(
    tmp_path, monkeypatch
):
    missing_policy = tmp_path / "missing-policy.json"
    malformed_policy = tmp_path / "malformed-policy.json"
    malformed_policy.write_text("{", encoding="utf-8")
    client = TestClient(
        create_app(
            model_partition_policy_path=missing_policy,
            model_partition_artifact_root=tmp_path / "artifacts",
        )
    )
    malformed_client = TestClient(
        create_app(
            model_partition_policy_path=malformed_policy,
            model_partition_artifact_root=tmp_path / "malformed-artifacts",
        )
    )

    contract_response = client.get("/api/model-partition/strategies")
    malformed_response = malformed_client.get("/api/model-partition/strategies")
    monkeypatch.setattr(
        "aiops_k8s_agents.control_plane_web.PartitionStrategyRegistry.default",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(
                "strategy-secret-must-not-leak "
                "C:\\Users\\private\\policy.json /home/private/policy.json"
            )
        ),
    )
    unexpected_response = client.get("/api/model-partition/strategies")

    assert contract_response.status_code == 400
    assert contract_response.json()["error_code"] == "invalid_partition_policy"
    assert malformed_response.status_code == 400
    assert malformed_response.json()["error_code"] == "invalid_partition_policy"
    assert unexpected_response.status_code == 500
    assert unexpected_response.json() == {
        "error_code": "internal_error",
        "message": "model partition request could not be completed",
    }


def test_strategy_catalog_hides_windows_and_posix_policy_paths(tmp_path):
    policy_paths = (
        r"C:\\Users\\private\\partition-policy.json",
        "/home/private/partition-policy.json",
    )

    for policy_path in policy_paths:
        client = TestClient(
            create_app(
                model_partition_policy_path=policy_path,
                model_partition_artifact_root=tmp_path / "artifacts",
            )
        )

        response = client.get("/api/model-partition/strategies")

        assert response.status_code == 400
        assert response.json() == {
            "error_code": "invalid_partition_policy",
            "message": "strategy policy could not be loaded",
        }
        response_text = response.text.lower()
        assert "c:\\" not in response_text
        assert "users" not in response_text
        assert "/home/" not in response_text
        assert "private" not in response_text

import json
from pathlib import Path

from fastapi.testclient import TestClient

from aiops_k8s_agents.control_plane_web import create_app


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

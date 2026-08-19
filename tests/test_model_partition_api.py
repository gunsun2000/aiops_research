import json
from pathlib import Path

from fastapi.testclient import TestClient

from aiops_k8s_agents.control_plane_web import create_app


def _example_payload() -> dict:
    return json.loads(
        Path("config/examples/model_partition_job.json").read_text(encoding="utf-8")
    )


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


def test_model_partition_plan_api_returns_stable_contract_error(tmp_path):
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

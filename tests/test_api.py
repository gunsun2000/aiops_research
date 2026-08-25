from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from orchestrator_agent.web import create_app


ROOT = Path(__file__).parents[1]


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        policy_path=ROOT / "config" / "model_partition_policy.json",
        artifact_root=tmp_path / "plans",
        example_root=ROOT / "config" / "examples",
        static_root=ROOT / "ui",
    )
    return TestClient(app)


def _federated_coordination_payload() -> dict[str, object]:
    plan = json.loads(
        (ROOT / "config" / "examples" / "federated_coordination_fl_v04.json").read_text(
            encoding="utf-8"
        )
    )
    context = json.loads(
        (
            ROOT
            / "config"
            / "examples"
            / "federated_coordination_context_v04.json"
        ).read_text(encoding="utf-8")
    )
    return {"coordination_plan": plan, "context": context}


def test_health_examples_and_ui_are_served(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/healthz").json() == {
        "status": "ok",
        "service": "Orchestrator-Agent",
    }
    examples = client.get("/api/examples").json()["examples"]
    assert {item["id"] for item in examples} >= {"fl-v04", "sl-v04", "inference-v04"}
    assert "Orchestrator-Agent" in client.get("/").text


def test_federated_coordination_plan_is_persisted_and_retrievable(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/coordination-plans",
        json=_federated_coordination_payload(),
    )

    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "planned"
    assert report["context_enrichment"]["status"] == "complete"
    assert report["scheduling_handoff"]["status"] == "ready"
    plan_id = report["plan"]["plan_id"]
    assert client.get(f"/api/plans/{plan_id}").json()["plan"]["plan_id"] == plan_id
    assert len(client.get(f"/api/plans/{plan_id}/history").json()["plans"]) == 1


def test_plan_catalog_is_empty_without_persisted_artifacts(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/plans")

    assert response.status_code == 200
    assert response.json() == {"plans": []}


def test_plan_catalog_summarizes_a_persisted_plan(tmp_path: Path) -> None:
    client = _client(tmp_path)
    report = client.post(
        "/api/coordination-plans",
        json=_federated_coordination_payload(),
    ).json()

    response = client.get("/api/plans")

    assert response.status_code == 200
    assert response.json() == {
        "plans": [
            {
                "plan_id": report["plan"]["plan_id"],
                "plan_version": 1,
                "parent_plan_id": None,
                "plan_type": "training",
                "strategy_id": "federated-full-model-v1",
                "execution_mode": "federated_learning",
                "status": "planned",
                "validation_status": "passed",
                "handoff_status": "ready",
                "created_at": report["scheduling_handoff"]["created_at"],
            }
        ]
    }


def test_persisted_plan_download_has_a_stable_json_attachment(tmp_path: Path) -> None:
    client = _client(tmp_path)
    report = client.post(
        "/api/coordination-plans",
        json=_federated_coordination_payload(),
    ).json()
    plan_id = report["plan"]["plan_id"]

    response = client.get(f"/api/plans/{plan_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{plan_id}.json"'
    )
    assert response.json()["plan"]["plan_id"] == plan_id


def test_strategy_and_ranker_catalogs_are_available(tmp_path: Path) -> None:
    client = _client(tmp_path)

    strategies = client.get("/api/strategies").json()["strategies"]
    assert {item["strategy_id"] for item in strategies} == {
        "federated-full-model-v1",
        "inference-partition-v1",
        "training-partition-v1",
    }
    assert client.get("/api/rankers").json() == {"rankers": []}

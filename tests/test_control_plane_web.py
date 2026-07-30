from __future__ import annotations

from fastapi.testclient import TestClient

from aiops_k8s_agents.control_plane_web import app


client = TestClient(app)


def test_scenario_experiment_api_creates_and_reads_session():
    response = client.post(
        "/api/experiments/mock",
        json={"scenario_id": "network-delay", "backend": "python"},
    )

    assert response.status_code == 200
    created = response.json()
    assert created["condition"]["scenario"] == "network-delay"
    assert created["condition"]["metric_values"]["latency"] == 0.234
    assert created["guard_backend"] == "python"
    assert created["stages"]["execution"]["status"] == "completed"

    fetched = client.get(
        f"/api/experiments/{created['experiment_id']}"
    )

    assert fetched.status_code == 200
    assert fetched.json() == created


def test_scenario_experiment_api_rejects_unknown_scenario():
    response = client.post(
        "/api/experiments/mock",
        json={"scenario_id": "disk-pressure", "backend": "python"},
    )

    assert response.status_code == 400
    assert "unknown scenario" in response.json()["detail"]


def test_scenario_experiment_api_returns_not_found_for_unknown_session():
    response = client.get("/api/experiments/not-a-real-session")

    assert response.status_code == 404

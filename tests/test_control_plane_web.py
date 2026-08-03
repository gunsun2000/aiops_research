from __future__ import annotations

from fastapi.testclient import TestClient

from aiops_k8s_agents.control_plane_web import app, create_app


client = TestClient(app)


def test_platform_capabilities_describe_current_runtime_boundary():
    response = client.get("/api/platform")

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_version"] == "1.0"
    assert payload["capabilities"]["persistent_jobs"] is False
    assert payload["capabilities"]["real_runtime"] is True
    assert payload["runtime_modes"]["mock"]["ready"] is True
    assert payload["runtime_modes"]["dry-run"]["ready"] is True
    assert "required_connections" in payload["runtime_modes"]["real"]


def test_validate_experiment_rejects_real_target_outside_allowlist():
    response = client.post(
        "/api/experiments/validate",
        json={
            "scenario_id": "cpu-stress",
            "namespace": "default",
            "deployment": "unknown",
            "metric": "cpu",
            "threshold": 80,
            "mode": "real",
            "backend": "python",
            "protocol_profile": "four-agent-role-veto-v1",
        },
    )

    assert response.status_code == 400
    assert "allowlist" in response.json()["detail"]


def test_connections_use_injected_readiness_checks_without_runtime_io(tmp_path):
    checks = {
        name: (lambda name=name: {"ready": name != "prometheus"})
        for name in (
            "kubernetes",
            "prometheus",
            "chaos_mesh",
            "autogen",
            "aiopslab",
            "artifact_directory",
        )
    }
    test_app = create_app(connection_probes=checks)

    response = TestClient(test_app).get("/api/connections")

    assert response.status_code == 200
    payload = response.json()
    assert payload["connections"]["kubernetes"]["ready"] is True
    assert payload["connections"]["prometheus"]["ready"] is False
    assert payload["missing_prerequisites"] == ["prometheus"]


def test_validate_experiment_is_preflight_only_for_mock_mode():
    class RuntimeMustNotRun:
        def run(self, _request):
            raise AssertionError("validation must not execute an experiment")

    test_app = create_app(runtime_factory=lambda: RuntimeMustNotRun())
    response = TestClient(test_app).post(
        "/api/experiments/validate",
        json={
            "scenario_id": "cpu-stress",
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "metric": "cpu",
            "threshold": 80,
            "mode": "mock",
            "backend": "python",
            "protocol_profile": "four-agent-role-veto-v1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["validated"] is True
    assert payload["resolved"]["mode"] == "mock"
    assert payload["controller"] == "mutual_supervision"
    assert payload["safety_bounds"]["min_replicas"] == 1
    assert payload["safety_bounds"]["max_replicas"] == 5


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

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import monotonic, sleep

from fastapi.testclient import TestClient

from aiops_k8s_agents.control_plane_web import app, create_app
from aiops_k8s_agents.autogen_groupchat import parse_autogen_decision
from aiops_k8s_agents.experiment_runtime import RuntimePreflightResult
from aiops_k8s_agents.experiment_runtime_models import RuntimeEvent, RuntimeStage


client = TestClient(app)


def test_platform_capabilities_describe_current_runtime_boundary():
    response = TestClient(create_app(connection_probes=_all_ready_probes())).get(
        "/api/platform"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_version"] == "1.0"
    assert payload["capabilities"]["persistent_jobs"] is True
    assert payload["capabilities"]["real_runtime"] is True
    assert payload["capabilities"]["fault_injection_api"] is True
    assert payload["runtime_modes"]["mock"]["ready"] is True
    assert payload["runtime_modes"]["dry-run"]["ready"] is True
    assert "required_connections" in payload["runtime_modes"]["real"]
    assert payload["runtime_modes"]["real"]["ready"] is False


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


def test_connections_expose_safe_autogen_readiness_reason():
    probes = _all_ready_probes()
    probes["autogen"] = lambda: {
        "ready": False,
        "status": "missing_credentials",
        "reason": "OpenAI credentials are not configured",
    }

    payload = TestClient(create_app(connection_probes=probes)).get(
        "/api/connections"
    ).json()

    assert payload["connections"]["autogen"] == {
        "ready": False,
        "required_for_real": False,
        "status": "missing_credentials",
        "reason": "OpenAI credentials are not configured",
    }


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


def test_validate_autogen_requires_ready_connection():
    probes = _all_ready_probes()
    probes["autogen"] = lambda: {
        "ready": False,
        "status": "missing_credentials",
        "reason": "OpenAI credentials are not configured",
    }
    test_app = create_app(connection_probes=probes)

    response = TestClient(test_app).post(
        "/api/experiments/validate",
        json=_job_payload(
            controller="autogen",
            model="fake-research-model",
            protocol_profile="four-agent-autogen-v1",
        ),
    )

    assert response.status_code == 400
    assert "AutoGen runtime is not ready" in response.json()["detail"]


def test_validate_autogen_resolves_controller_model_and_profile():
    response = TestClient(
        create_app(connection_probes=_all_ready_probes())
    ).post(
        "/api/experiments/validate",
        json=_job_payload(
            controller="autogen",
            model=" fake-research-model ",
            protocol_profile="four-agent-autogen-v1",
        ),
    )

    assert response.status_code == 200
    resolved = response.json()["resolved"]
    assert resolved["controller"] == "autogen"
    assert resolved["model"] == "fake-research-model"
    assert resolved["protocol_profile"] == "four-agent-autogen-v1"


def _all_ready_probes():
    return {
        name: (lambda: {"ready": True})
        for name in (
            "kubernetes",
            "prometheus",
            "chaos_mesh",
            "autogen",
            "aiopslab",
            "artifact_directory",
        )
    }


def _real_validation_payload():
    return {
        "scenario_id": "cpu-stress",
        "namespace": "online-boutique",
        "deployment": "paymentservice",
        "metric": "cpu",
        "threshold": 80,
        "mode": "real",
        "backend": "python",
        "protocol_profile": "four-agent-role-veto-v1",
    }


def test_validate_real_calls_request_specific_preflight_and_accepts_registered_prerequisites():
    calls = []

    class Runtime:
        def preflight(self, request):
            calls.append(("preflight", request))
            return RuntimePreflightResult(
                valid=True,
                scenario_id=request.scenario_id,
                manifest="k8s/chaos/paymentservice-cpu-stress.yaml",
                resource_kind="StressChaos",
            )

        def run(self, _request):
            calls.append("run")
            raise AssertionError("real validation must not execute runtime")

    test_app = create_app(
        runtime_factory=lambda: (calls.append("factory") or Runtime()),
        connection_probes=_all_ready_probes(),
    )
    response = TestClient(test_app).post(
        "/api/experiments/validate", json=_real_validation_payload()
    )

    assert response.status_code == 200
    assert response.json()["validated"] is True
    assert response.json()["preflight"]["resource_kind"] == "StressChaos"
    assert [call if call == "factory" else call[0] for call in calls] == [
        "factory", "preflight"
    ]


def test_validate_real_rejects_scenario_specific_resource_prerequisite():
    class Runtime:
        def preflight(self, _request):
            return RuntimePreflightResult(
                valid=False,
                scenario_id="cpu-stress",
                manifest="k8s/chaos/paymentservice-cpu-stress.yaml",
                resource_kind="StressChaos",
                missing_prerequisites=("chaos_mesh.resource_kind:StressChaos",),
            )

    test_app = create_app(
        runtime_factory=lambda: Runtime(),
        connection_probes=_all_ready_probes(),
    )
    response = TestClient(test_app).post(
        "/api/experiments/validate", json=_real_validation_payload()
    )

    assert response.status_code == 400
    assert "chaos_mesh.resource_kind:StressChaos" in response.json()["detail"]


def test_validate_real_sanitizes_preflight_exception_and_performs_no_mutation():
    mutations = []

    class Runtime:
        def preflight(self, _request):
            raise RuntimeError("Authorization token SECRET-DO-NOT-LEAK")

        def run(self, _request):
            mutations.append("run")

        def apply(self):
            mutations.append("apply")

        def delete(self):
            mutations.append("delete")

    test_app = create_app(
        runtime_factory=lambda: Runtime(),
        connection_probes=_all_ready_probes(),
    )
    response = TestClient(test_app).post(
        "/api/experiments/validate", json=_real_validation_payload()
    )

    assert response.status_code == 400
    assert "SECRET-DO-NOT-LEAK" not in response.text
    assert "runtime preflight failed" in response.json()["detail"]
    assert mutations == []


def test_validate_real_sanitizes_runtime_factory_exception():
    test_app = create_app(
        runtime_factory=lambda: (_ for _ in ()).throw(
            RuntimeError("API_KEY=SECRET-DO-NOT-LEAK")
        ),
        connection_probes=_all_ready_probes(),
    )
    response = TestClient(test_app).post(
        "/api/experiments/validate", json=_real_validation_payload()
    )

    assert response.status_code == 400
    assert "SECRET-DO-NOT-LEAK" not in response.text
    assert response.json()["detail"] == "runtime preflight failed"


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


@dataclass
class _JobRuntimeResult:
    experiment_id: str
    status: str = "recovered"

    def to_dict(self):
        return {
            "experiment_id": self.experiment_id,
            "status": self.status,
            "session": {"experiment_id": self.experiment_id},
        }


class _JobRuntime:
    def __init__(self, sink, cancellation, experiment_id, *, block=False):
        self.sink = sink
        self.cancellation = cancellation
        self.experiment_id = experiment_id
        self.block = block

    def run(self, _request):
        self.sink.emit(
            RuntimeEvent(
                experiment_id=self.experiment_id,
                sequence=1,
                stage=RuntimeStage.PREFLIGHT,
                status="running",
                message="runtime preflight",
                created_at="2026-08-03T03:00:00+00:00",
            )
        )
        if self.block:
            self.cancellation.wait(timeout=2.0)
            return _JobRuntimeResult(self.experiment_id, "cancelled")
        self.sink.emit(
            RuntimeEvent(
                experiment_id=self.experiment_id,
                sequence=2,
                stage=RuntimeStage.COLLECTING_EVIDENCE,
                status="running",
                message="collecting registered evidence",
                created_at="2026-08-03T03:00:01+00:00",
            )
        )
        return _JobRuntimeResult(self.experiment_id)


def _job_payload(**overrides):
    payload = {
        "scenario_id": "cpu-stress",
        "namespace": "online-boutique",
        "deployment": "paymentservice",
        "metric": "cpu",
        "threshold": 80,
        "mode": "mock",
        "backend": "python",
        "protocol_profile": "four-agent-role-veto-v1",
        "repetitions": 1,
    }
    payload.update(overrides)
    return payload


def _wait_for_job(client, experiment_id, timeout=2.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        response = client.get(f"/api/experiments/{experiment_id}")
        if response.status_code == 200 and response.json()["status"] in {
            "completed",
            "failed",
            "blocked",
            "cancelled",
            "interrupted",
        }:
            return response.json()
        sleep(0.01)
    raise AssertionError("job did not become terminal")


def _autogen_decisions(replicas="3"):
    payloads = (
        (
            "AIServiceHASupportAgent",
            "ha_scale_out_required",
            0.90,
            "HA evidence requires bounded recovery.",
        ),
        (
            "AIApplicationManagementAgent",
            "app_scale_deployment",
            0.85,
            "Scale the saturated application deployment.",
        ),
        (
            "AISemiconductorInfraOpsAgent",
            "infra_capacity_approved",
            0.70,
            "The proposal fits infrastructure policy.",
        ),
        (
            "CostOptimizationAgent",
            "cost_budget_approved",
            0.60,
            "The proposal fits cost policy.",
        ),
    )
    return [
        parse_autogen_decision(
            {
                "agent": agent,
                "action": action,
                "reward": reward,
                "approved": True,
                "reason": reason,
                "parameters": {
                    "namespace": "online-boutique",
                    "deployment": "paymentservice",
                    "replicas": replicas,
                },
            },
            expected_agent=agent,
        )
        for agent, action, reward, reason in payloads
    ]


def test_create_experiment_runs_in_background_and_lists_job(tmp_path):
    test_app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        job_runtime_factory=lambda sink, cancellation, experiment_id: _JobRuntime(
            sink, cancellation, experiment_id
        ),
    )
    test_client = TestClient(test_app)

    response = test_client.post("/api/experiments", json=_job_payload())

    assert response.status_code == 202
    experiment_id = response.json()["experiment_id"]
    finished = _wait_for_job(test_client, experiment_id)
    listed = test_client.get("/api/experiments?limit=10")

    assert finished["status"] == "completed"
    assert finished["request"]["scenario_id"] == "cpu-stress"
    assert finished["result"]["successful_attempts"] == 1
    assert listed.status_code == 200
    assert listed.json()["jobs"][0]["experiment_id"] == experiment_id


def test_create_autogen_experiment_runs_registered_bounded_runtime(tmp_path):
    requested_models = []

    def provider_factory(model):
        requested_models.append(model)
        return lambda _alert: _autogen_decisions()

    test_app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        connection_probes=_all_ready_probes(),
        autogen_decision_provider_factory=provider_factory,
    )
    test_client = TestClient(test_app)

    created = test_client.post(
        "/api/experiments",
        json=_job_payload(
            controller="autogen",
            model="fake-research-model",
            protocol_profile="four-agent-autogen-v1",
        ),
    )

    assert created.status_code == 202
    finished = _wait_for_job(test_client, created.json()["experiment_id"])
    report = finished["result"]["attempts"][0]["report"]
    assert finished["status"] == "completed"
    assert finished["request"]["controller"] == "autogen"
    assert report["controller"] == "autogen"
    assert report["model"] == "fake-research-model"
    assert requested_models == ["fake-research-model"]


def test_create_experiment_rejects_unknown_scenario_before_job_creation(tmp_path):
    test_app = create_app(job_database_path=tmp_path / "jobs.sqlite3")

    response = TestClient(test_app).post(
        "/api/experiments",
        json=_job_payload(scenario_id="unknown-scenario"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown scenario"
    assert TestClient(test_app).get("/api/experiments").json()["jobs"] == []


def test_real_experiment_requires_server_gate_and_exact_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIRM_REAL_RUN", "YES")
    test_app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        connection_probes=_all_ready_probes(),
    )

    response = TestClient(test_app).post(
        "/api/experiments",
        json=_job_payload(mode="real"),
    )

    assert response.status_code == 400
    assert "EXECUTE REAL EXPERIMENT" in response.json()["detail"]


def test_cancel_endpoint_signals_running_job(tmp_path):
    runtime_started = Event()

    def runtime_factory(sink, cancellation, experiment_id):
        runtime_started.set()
        return _JobRuntime(sink, cancellation, experiment_id, block=True)

    test_app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        job_runtime_factory=runtime_factory,
    )
    test_client = TestClient(test_app)
    created = test_client.post("/api/experiments", json=_job_payload()).json()
    assert runtime_started.wait(timeout=1.0)

    cancelled = test_client.post(
        f"/api/experiments/{created['experiment_id']}/cancel"
    )
    finished = _wait_for_job(test_client, created["experiment_id"])

    assert cancelled.status_code == 202
    assert cancelled.json()["cancel_requested"] is True
    assert finished["status"] == "cancelled"


def test_app_shutdown_cancels_running_background_jobs(tmp_path):
    runtime_started = Event()
    cancellation_seen = Event()

    class ShutdownAwareRuntime:
        def __init__(self, cancellation, experiment_id):
            self.cancellation = cancellation
            self.experiment_id = experiment_id

        def run(self, _request):
            runtime_started.set()
            if self.cancellation.wait(timeout=5.0):
                cancellation_seen.set()
                return _JobRuntimeResult(self.experiment_id, "cancelled")
            return _JobRuntimeResult(self.experiment_id, "failed")

    test_app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        job_runtime_factory=lambda _sink, cancellation, experiment_id: (
            ShutdownAwareRuntime(cancellation, experiment_id)
        ),
    )

    with TestClient(test_app) as test_client:
        created = test_client.post("/api/experiments", json=_job_payload()).json()
        assert runtime_started.wait(timeout=1.0)

    assert cancellation_seen.is_set()
    assert (
        test_app.state.runtime_api.job_store.get(created["experiment_id"]).status.value
        == "cancelled"
    )


def test_sse_replays_events_after_last_event_id_and_finishes(tmp_path):
    test_app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        job_runtime_factory=lambda sink, cancellation, experiment_id: _JobRuntime(
            sink, cancellation, experiment_id
        ),
    )
    test_client = TestClient(test_app)
    created = test_client.post("/api/experiments", json=_job_payload()).json()
    _wait_for_job(test_client, created["experiment_id"])

    response = test_client.get(
        f"/api/experiments/{created['experiment_id']}/events",
        headers={"Last-Event-ID": "1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 2" in response.text
    assert "collecting registered evidence" in response.text
    assert "runtime preflight" not in response.text
    assert "event: job" in response.text


def test_unknown_persistent_job_returns_not_found(tmp_path):
    test_app = create_app(job_database_path=tmp_path / "jobs.sqlite3")

    response = TestClient(test_app).get("/api/experiments/exp-missing")

    assert response.status_code == 404

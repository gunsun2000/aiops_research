from __future__ import annotations

from fastapi.testclient import TestClient

from aiops_k8s_agents import experiment_bulk_delete as _experiment_bulk_delete  # noqa: F401
from aiops_k8s_agents.control_plane_web import create_app
from aiops_k8s_agents.experiment_jobs import ExperimentJobStatus
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode


def _request() -> ExperimentRuntimeRequest:
    return ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode=ExecutionMode.MOCK,
        backend=ExecutionBackend.PYTHON,
        protocol_profile="four-agent-role-veto-v1",
    )


def _completed_job(app, experiment_id: str, artifact: str | None = None):
    store = app.state.runtime_api.job_store
    store.create(_request(), experiment_id=experiment_id)
    report = {"final_status": "recovered"}
    if artifact is not None:
        report["artifacts"] = {"json": artifact}
    return store.set_result(
        experiment_id,
        status=ExperimentJobStatus.COMPLETED,
        result={
            "experiment_id": experiment_id,
            "status": "completed",
            "attempts": [
                {
                    "experiment_id": f"{experiment_id}-r01",
                    "status": "recovered",
                    "report": report,
                }
            ],
        },
    )


def test_delete_experiment_removes_terminal_job_and_owned_artifact(tmp_path):
    artifact_root = tmp_path / "experiment-artifacts"
    artifact_root.mkdir()
    artifact = artifact_root / "exp-delete" / "report.json"
    artifact.parent.mkdir()
    artifact.write_text('{"status":"recovered"}', encoding="utf-8")
    app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        experiment_artifact_root=artifact_root,
    )
    _completed_job(app, "exp-delete", str(artifact))

    with TestClient(app) as client:
        response = client.delete("/api/experiments/exp-delete")

    assert response.status_code == 200
    assert response.json() == {
        "deleted": True,
        "experiment_id": "exp-delete",
        "artifacts_deleted": 1,
    }
    assert app.state.runtime_api.job_store.get("exp-delete") is None
    assert not artifact.exists()


def test_delete_experiment_returns_404_for_missing_job(tmp_path):
    app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        experiment_artifact_root=tmp_path / "experiment-artifacts",
    )

    with TestClient(app) as client:
        response = client.delete("/api/experiments/exp-missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "experiment not found"


def test_delete_experiment_rejects_nonterminal_job(tmp_path):
    app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        experiment_artifact_root=tmp_path / "experiment-artifacts",
    )
    store = app.state.runtime_api.job_store
    store.create(_request(), experiment_id="exp-running")
    store.transition("exp-running", ExperimentJobStatus.RUNNING)

    with TestClient(app) as client:
        response = client.delete("/api/experiments/exp-running")

    assert response.status_code == 409
    assert response.json()["detail"] == "experiment is not terminal"
    assert store.get("exp-running") is not None


def test_delete_experiment_never_removes_artifact_outside_allowed_root(tmp_path):
    artifact_root = tmp_path / "experiment-artifacts"
    artifact_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("must remain", encoding="utf-8")
    app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        experiment_artifact_root=artifact_root,
    )
    _completed_job(app, "exp-unsafe", str(outside))

    with TestClient(app) as client:
        response = client.delete("/api/experiments/exp-unsafe")

    assert response.status_code == 409
    assert "outside the allowed root" in response.json()["detail"]
    assert outside.read_text(encoding="utf-8") == "must remain"
    assert app.state.runtime_api.job_store.get("exp-unsafe") is not None


def test_bulk_delete_experiments_removes_terminal_jobs_and_preserves_active_jobs(tmp_path):
    artifact_root = tmp_path / "experiment-artifacts"
    artifact_root.mkdir()
    app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        experiment_artifact_root=artifact_root,
    )
    first = artifact_root / "exp-one" / "report.json"
    first.parent.mkdir()
    first.write_text("one", encoding="utf-8")
    second = artifact_root / "exp-two" / "report.json"
    second.parent.mkdir()
    second.write_text("two", encoding="utf-8")
    _completed_job(app, "exp-one", str(first))
    _completed_job(app, "exp-two", str(second))
    store = app.state.runtime_api.job_store
    store.create(_request(), experiment_id="exp-running")
    store.transition("exp-running", ExperimentJobStatus.RUNNING)

    with TestClient(app) as client:
        response = client.delete("/api/experiments")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == 2
    assert payload["artifacts_deleted"] == 2
    assert payload["protected_active"] == 1
    assert set(payload["deleted_experiment_ids"]) == {"exp-one", "exp-two"}
    assert store.get("exp-one") is None
    assert store.get("exp-two") is None
    assert store.get("exp-running") is not None
    assert not first.exists()
    assert not second.exists()


def test_bulk_delete_experiments_returns_immediately_when_only_active_jobs_exist(tmp_path):
    app = create_app(
        job_database_path=tmp_path / "jobs.sqlite3",
        experiment_artifact_root=tmp_path / "experiment-artifacts",
    )
    store = app.state.runtime_api.job_store
    store.create(_request(), experiment_id="exp-running")
    store.transition("exp-running", ExperimentJobStatus.RUNNING)

    with TestClient(app) as client:
        response = client.delete("/api/experiments")

    assert response.status_code == 200
    assert response.json() == {
        "deleted": 0,
        "artifacts_deleted": 0,
        "protected_active": 1,
        "deleted_experiment_ids": [],
    }
    assert store.get("exp-running") is not None

from __future__ import annotations

from aiops_k8s_agents.experiment_jobs import (
    ExperimentJobStatus,
    SQLiteExperimentJobStore,
)
from aiops_k8s_agents.experiment_runtime_models import (
    ExperimentRuntimeRequest,
    RuntimeEvent,
    RuntimeStage,
)
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
        repetitions=3,
    )


def test_job_request_round_trips_through_sqlite(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")

    created = store.create(_request(), experiment_id="exp-roundtrip")
    loaded = store.get("exp-roundtrip")

    assert created.experiment_id == "exp-roundtrip"
    assert loaded is not None
    assert loaded.request.to_dict() == {
        "scenario_id": "cpu-stress",
        "namespace": "online-boutique",
        "deployment": "paymentservice",
        "metric": "cpu",
        "threshold": 80.0,
        "mode": "mock",
        "backend": "python",
        "protocol_profile": "four-agent-role-veto-v1",
        "repetitions": 3,
    }
    assert loaded.status is ExperimentJobStatus.QUEUED
    assert loaded.current_stage == RuntimeStage.QUEUED.value
    assert store.list(limit=10) == (loaded,)


def test_job_transitions_and_events_are_persisted_in_sequence(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")
    store.create(_request(), experiment_id="exp-events")
    store.transition(
        "exp-events",
        ExperimentJobStatus.RUNNING,
        current_stage=RuntimeStage.PREFLIGHT.value,
    )
    store.append_event(
        RuntimeEvent(
            experiment_id="exp-events",
            sequence=1,
            stage=RuntimeStage.PREFLIGHT,
            status="running",
            message="runtime preflight",
            created_at="2026-08-03T01:00:00+00:00",
        )
    )
    store.append_event(
        RuntimeEvent(
            experiment_id="exp-events",
            sequence=2,
            stage=RuntimeStage.COLLECTING_EVIDENCE,
            status="running",
            message="collecting registered evidence",
            created_at="2026-08-03T01:00:01+00:00",
            payload={"source": "fake"},
        )
    )

    job = store.get("exp-events")
    events = store.events_after("exp-events", sequence=1)

    assert job is not None
    assert job.status is ExperimentJobStatus.RUNNING
    assert job.current_stage == RuntimeStage.COLLECTING_EVIDENCE.value
    assert [event.sequence for event in events] == [2]
    assert events[0].payload == {"source": "fake"}


def test_cancel_request_survives_store_reopen(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    store = SQLiteExperimentJobStore(database)
    store.create(_request(), experiment_id="exp-cancel")
    store.transition("exp-cancel", ExperimentJobStatus.RUNNING)

    cancelled = store.request_cancel("exp-cancel")
    reopened = SQLiteExperimentJobStore(database).get("exp-cancel")

    assert cancelled.status is ExperimentJobStatus.CANCELLING
    assert cancelled.cancel_requested is True
    assert reopened is not None
    assert reopened.status is ExperimentJobStatus.CANCELLING
    assert reopened.cancel_requested is True


def test_restart_interrupts_only_nonterminal_jobs(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")
    for experiment_id in ("exp-queued", "exp-running", "exp-finished"):
        store.create(_request(), experiment_id=experiment_id)
    store.transition("exp-running", ExperimentJobStatus.RUNNING)
    store.set_result(
        "exp-finished",
        status=ExperimentJobStatus.COMPLETED,
        result={"status": "recovered"},
    )

    interrupted = store.interrupt_nonterminal_jobs()

    assert interrupted == ("exp-queued", "exp-running")
    assert store.get("exp-queued").status is ExperimentJobStatus.INTERRUPTED
    assert store.get("exp-running").status is ExperimentJobStatus.INTERRUPTED
    assert store.get("exp-finished").status is ExperimentJobStatus.COMPLETED
    assert store.get("exp-finished").result == {"status": "recovered"}

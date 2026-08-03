from datetime import UTC, datetime

import pytest

from aiops_k8s_agents.aiopslab_jobs import (
    AIOpsLabBenchmarkRequest,
    SQLiteAIOpsLabJobStore,
)
from aiops_k8s_agents.experiment_jobs import ExperimentJobStatus
from aiops_k8s_agents.experiment_runtime_models import RuntimeEvent, RuntimeStage


def _event(job_id: str, sequence: int, message: str = "benchmark event") -> RuntimeEvent:
    return RuntimeEvent(
        experiment_id=job_id,
        sequence=sequence,
        stage=RuntimeStage.ANALYZING,
        status="running",
        message=message,
        created_at=datetime.now(UTC).isoformat(),
        payload={"sequence": sequence},
    )


def test_aiopslab_benchmark_request_normalizes_and_validates_bounds():
    request = AIOpsLabBenchmarkRequest(
        benchmark_id=" hotel-reservation-detection-v1 ",
        repetitions=3,
    )

    assert request.benchmark_id == "hotel-reservation-detection-v1"
    assert request.to_dict() == {
        "benchmark_id": "hotel-reservation-detection-v1",
        "repetitions": 3,
    }

    with pytest.raises(ValueError, match="benchmark_id"):
        AIOpsLabBenchmarkRequest(benchmark_id="../outside", repetitions=1)
    with pytest.raises(ValueError, match="1..12"):
        AIOpsLabBenchmarkRequest(benchmark_id="registered", repetitions=13)


def test_aiopslab_job_store_round_trips_request_events_and_result(tmp_path):
    store = SQLiteAIOpsLabJobStore(tmp_path / "jobs.sqlite3")
    request = AIOpsLabBenchmarkRequest(
        benchmark_id="hotel-reservation-detection-v1",
        repetitions=3,
    )

    created = store.create(request, job_id="lab-job-001")
    store.transition(created.job_id, ExperimentJobStatus.RUNNING)
    store.append_event(_event(created.job_id, 2, "second"))
    store.append_event(_event(created.job_id, 1, "first"))
    finished = store.set_result(
        created.job_id,
        status=ExperimentJobStatus.COMPLETED,
        result={"total_runs": 3, "correct_runs": 3},
    )

    restored = SQLiteAIOpsLabJobStore(tmp_path / "jobs.sqlite3").get(created.job_id)
    assert restored is not None
    assert restored.request == request
    assert restored.result == {"total_runs": 3, "correct_runs": 3}
    assert restored.status is ExperimentJobStatus.COMPLETED
    assert finished.finished_at
    assert [event.message for event in store.events_after(created.job_id)] == [
        "first",
        "second",
    ]


def test_aiopslab_job_store_marks_cancel_request_without_finishing_job(tmp_path):
    store = SQLiteAIOpsLabJobStore(tmp_path / "jobs.sqlite3")
    job = store.create(
        AIOpsLabBenchmarkRequest("hotel-reservation-detection-v1"),
        job_id="lab-job-cancel",
    )

    cancelling = store.request_cancel(job.job_id)

    assert cancelling.cancel_requested is True
    assert cancelling.status is ExperimentJobStatus.CANCELLING
    assert cancelling.finished_at is None


def test_aiopslab_job_store_interrupts_nonterminal_jobs_on_restart(tmp_path):
    store = SQLiteAIOpsLabJobStore(tmp_path / "jobs.sqlite3")
    first = store.create(
        AIOpsLabBenchmarkRequest("hotel-reservation-detection-v1"),
        job_id="lab-job-running",
    )
    second = store.create(
        AIOpsLabBenchmarkRequest("hotel-reservation-detection-v1"),
        job_id="lab-job-complete",
    )
    store.transition(first.job_id, ExperimentJobStatus.RUNNING)
    store.set_result(
        second.job_id,
        status=ExperimentJobStatus.COMPLETED,
        result={"total_runs": 1},
    )

    interrupted = store.interrupt_nonterminal_jobs()

    assert interrupted == (first.job_id,)
    assert store.get(first.job_id).status is ExperimentJobStatus.INTERRUPTED
    assert store.get(second.job_id).status is ExperimentJobStatus.COMPLETED


def test_aiopslab_job_store_rejects_duplicate_event_sequence(tmp_path):
    store = SQLiteAIOpsLabJobStore(tmp_path / "jobs.sqlite3")
    job = store.create(
        AIOpsLabBenchmarkRequest("hotel-reservation-detection-v1"),
        job_id="lab-job-events",
    )
    store.append_event(_event(job.job_id, 1))

    with pytest.raises(ValueError, match="event already exists"):
        store.append_event(_event(job.job_id, 1))

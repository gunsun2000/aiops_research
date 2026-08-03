from datetime import UTC, datetime

import pytest

from aiops_k8s_agents.experiment_jobs import ExperimentJobStatus
from aiops_k8s_agents.experiment_runtime_models import RuntimeEvent, RuntimeStage
from aiops_k8s_agents.recovery_comparison_jobs import (
    RecoveryComparisonRequest,
    SQLiteRecoveryComparisonJobStore,
)


def _event(job_id: str, sequence: int) -> RuntimeEvent:
    return RuntimeEvent(
        experiment_id=job_id,
        sequence=sequence,
        stage=RuntimeStage.ANALYZING,
        status="running",
        message=f"comparison event {sequence}",
        created_at=datetime.now(UTC).isoformat(),
        payload={"sequence": sequence},
    )


def test_comparison_request_validates_bounded_matrix_options():
    request = RecoveryComparisonRequest(
        repetitions=3,
        mode="mock",
        guard_backend="go",
    )

    assert request.to_dict() == {
        "repetitions": 3,
        "mode": "mock",
        "guard_backend": "go",
    }

    with pytest.raises(ValueError, match="1..3"):
        RecoveryComparisonRequest(repetitions=4)
    with pytest.raises(ValueError, match="mock or real"):
        RecoveryComparisonRequest(mode="dry-run")
    with pytest.raises(ValueError, match="python or go"):
        RecoveryComparisonRequest(guard_backend="shell")


def test_comparison_store_round_trips_job_events_and_result(tmp_path):
    store = SQLiteRecoveryComparisonJobStore(tmp_path / "jobs.sqlite3")
    request = RecoveryComparisonRequest(repetitions=3, mode="mock")
    created = store.create(request, job_id="comparison-job-001")
    store.transition(created.job_id, ExperimentJobStatus.RUNNING)
    store.append_event(_event(created.job_id, 2))
    store.append_event(_event(created.job_id, 1))
    store.set_result(
        created.job_id,
        status=ExperimentJobStatus.COMPLETED,
        result={"total_treatments": 36, "valid_measurements": 36},
    )

    restored = SQLiteRecoveryComparisonJobStore(tmp_path / "jobs.sqlite3").get(
        created.job_id
    )

    assert restored is not None
    assert restored.request == request
    assert restored.status is ExperimentJobStatus.COMPLETED
    assert restored.result["total_treatments"] == 36
    assert [event.sequence for event in store.events_after(created.job_id)] == [1, 2]


def test_comparison_store_interrupts_nonterminal_jobs(tmp_path):
    store = SQLiteRecoveryComparisonJobStore(tmp_path / "jobs.sqlite3")
    active = store.create(RecoveryComparisonRequest(), job_id="comparison-active")
    completed = store.create(
        RecoveryComparisonRequest(), job_id="comparison-completed"
    )
    store.transition(active.job_id, ExperimentJobStatus.RUNNING)
    store.set_result(
        completed.job_id,
        status=ExperimentJobStatus.COMPLETED,
        result={"total_treatments": 12},
    )

    interrupted = store.interrupt_nonterminal_jobs()

    assert interrupted == (active.job_id,)
    assert store.get(active.job_id).status is ExperimentJobStatus.INTERRUPTED
    assert store.get(completed.job_id).status is ExperimentJobStatus.COMPLETED

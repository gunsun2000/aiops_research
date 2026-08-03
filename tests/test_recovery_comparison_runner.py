from pathlib import Path
from threading import Event
from time import monotonic, sleep

from aiops_k8s_agents.experiment_jobs import ExperimentJobStatus
from aiops_k8s_agents.recovery_comparison_jobs import (
    RecoveryComparisonRequest,
    SQLiteRecoveryComparisonJobStore,
)
from aiops_k8s_agents.recovery_comparison_runner import (
    RecoveryComparisonExecutor,
    RecoveryComparisonJobRunner,
)


def _wait_terminal(store, job_id, timeout=4):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job = store.get(job_id)
        if job.status.terminal:
            return job
        sleep(0.01)
    raise AssertionError("comparison job did not finish")


def test_mock_comparison_generates_distinct_quantitative_artifacts(tmp_path):
    executor = RecoveryComparisonExecutor(
        repo_root=tmp_path,
        config_path=tmp_path / "unused.json",
    )
    result = executor.execute(
        job_id="comparison-mock",
        request=RecoveryComparisonRequest(repetitions=3, mode="mock"),
        output_dir=tmp_path / "runs" / "comparison-mock",
        cancellation=Event(),
        emit=lambda *_args, **_kwargs: None,
    )

    assert result["evidence_type"] == "synthetic_mock"
    assert result["total_treatments"] == 36
    assert result["valid_measurements"] == 36
    assert result["statistics"]["overall"]["success_rate"] < 1.0
    assert Path(result["artifacts"]["outcomes_jsonl"]).exists()
    assert Path(result["artifacts"]["quantitative_markdown"]).exists()
    assert Path(result["artifacts"]["success_rate_png"]).exists()
    rows = result["statistics"]["scenario_action_statistics"]
    assert len({row["success_rate"] for row in rows}) > 1


def test_comparison_runner_persists_progress_and_terminal_result(tmp_path):
    store = SQLiteRecoveryComparisonJobStore(tmp_path / "jobs.sqlite3")
    executor = RecoveryComparisonExecutor(
        repo_root=tmp_path,
        config_path=tmp_path / "unused.json",
    )
    runner = RecoveryComparisonJobRunner(
        store,
        executor,
        artifact_root=tmp_path / "runs",
        job_id_factory=lambda: "comparison-runner",
    )

    submitted = runner.submit(RecoveryComparisonRequest(repetitions=1, mode="mock"))
    finished = _wait_terminal(store, submitted.job_id)

    assert finished.status is ExperimentJobStatus.COMPLETED
    assert finished.result["total_treatments"] == 12
    assert any(
        event.payload.get("completed_treatments") == 12
        for event in store.events_after(submitted.job_id)
    )
    runner.shutdown()


class _BlockingComparisonExecutor:
    def __init__(self) -> None:
        self.started = Event()

    def readiness(self, mode="mock"):
        return {"ready": True, "mode": mode, "reasons": []}

    def execute(self, *, cancellation, **_kwargs):
        self.started.set()
        cancellation.wait(timeout=2)
        return {"cancelled": cancellation.is_set()}


def test_comparison_runner_cancels_active_job(tmp_path):
    store = SQLiteRecoveryComparisonJobStore(tmp_path / "jobs.sqlite3")
    executor = _BlockingComparisonExecutor()
    runner = RecoveryComparisonJobRunner(
        store,
        executor,
        artifact_root=tmp_path / "runs",
        job_id_factory=lambda: "comparison-cancel",
    )
    submitted = runner.submit(RecoveryComparisonRequest())
    assert executor.started.wait(timeout=1)

    runner.cancel(submitted.job_id)
    finished = _wait_terminal(store, submitted.job_id)

    assert finished.status is ExperimentJobStatus.CANCELLED
    runner.shutdown()

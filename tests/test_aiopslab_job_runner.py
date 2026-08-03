import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from aiops_k8s_agents.aiopslab_benchmark import (
    AIOpsLabBenchmarkCatalog,
    AIOpsLabExecutionCancelled,
    AIOpsLabExecutionResult,
)
from aiops_k8s_agents.aiopslab_job_runner import AIOpsLabJobRunner
from aiops_k8s_agents.aiopslab_jobs import (
    AIOpsLabBenchmarkRequest,
    SQLiteAIOpsLabJobStore,
)
from aiops_k8s_agents.experiment_jobs import ExperimentJobStatus


def _catalog(tmp_path: Path) -> AIOpsLabBenchmarkCatalog:
    path = tmp_path / "benchmarks.json"
    path.write_text(
        json.dumps(
            {
                "benchmarks": [
                    {
                        "id": "hotel-reservation-detection-v1",
                        "title": "Hotel Reservation Detection",
                        "problem_id": "misconfig_app_hotel_res-detection-1",
                        "namespace": "test-hotel-reservation",
                        "service": "geo",
                        "metrics_duration_minutes": 10,
                        "max_steps": 8,
                        "timeout_seconds": 30,
                        "max_repetitions": 12,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return AIOpsLabBenchmarkCatalog.from_path(path)


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def readiness(self) -> dict:
        return {"ready": True, "reasons": []}

    def execute(self, spec, *, job_id, repetition, output_dir, cancellation):
        self.calls.append((job_id, repetition))
        report_path = Path(output_dir) / (
            f"20260803-{repetition:02d}_aiopslab_auto_detection.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "problem_id": spec.problem_id,
                    "namespace": spec.namespace,
                    "service": spec.service,
                    "decisions": [
                        {
                            "api_call": 'submit("Yes")',
                            "metadata": {
                                "reward_total": "3.10",
                                "phase": "detection",
                            },
                            "observation_excerpt": (
                                "Metrics data exported to directory: /tmp/metric"
                            ),
                        }
                    ],
                    "aiopslab_results": {
                        "final_state": "SubmissionStatus.VALID_SUBMISSION",
                        "results": {
                            "Detection Accuracy": "Correct",
                            "TTD": float(repetition),
                            "steps": 3,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return AIOpsLabExecutionResult(
            report_path=report_path,
            returncode=0,
            stdout="completed",
            stderr="",
        )


class _BlockingExecutor(_FakeExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()

    def execute(self, spec, *, job_id, repetition, output_dir, cancellation):
        self.started.set()
        if cancellation.wait(timeout=2):
            raise AIOpsLabExecutionCancelled("benchmark cancelled")
        return super().execute(
            spec,
            job_id=job_id,
            repetition=repetition,
            output_dir=output_dir,
            cancellation=cancellation,
        )


def _wait_terminal(store, job_id, timeout=3):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job = store.get(job_id)
        if job.status.terminal:
            return job
        sleep(0.01)
    raise AssertionError("benchmark job did not finish")


def test_runner_repeats_benchmark_and_writes_aggregate_artifacts(tmp_path):
    store = SQLiteAIOpsLabJobStore(tmp_path / "jobs.sqlite3")
    executor = _FakeExecutor()
    runner = AIOpsLabJobRunner(
        store,
        _catalog(tmp_path),
        executor,
        artifact_root=tmp_path / "runs",
        job_id_factory=lambda: "lab-job-repeat",
    )

    submitted = runner.submit(
        AIOpsLabBenchmarkRequest("hotel-reservation-detection-v1", repetitions=3)
    )
    finished = _wait_terminal(store, submitted.job_id)

    assert finished.status is ExperimentJobStatus.COMPLETED
    assert finished.result["total_runs"] == 3
    assert finished.result["correct_runs"] == 3
    assert finished.result["average_ttd"] == 2.0
    assert len(executor.calls) == 3
    assert Path(finished.result["artifacts"]["markdown"]).exists()
    assert Path(finished.result["artifacts"]["csv"]).exists()
    events = store.events_after(submitted.job_id)
    assert any(event.payload.get("repetition") == 3 for event in events)
    runner.shutdown()


def test_runner_cancels_active_benchmark_without_starting_more_runs(tmp_path):
    store = SQLiteAIOpsLabJobStore(tmp_path / "jobs.sqlite3")
    executor = _BlockingExecutor()
    runner = AIOpsLabJobRunner(
        store,
        _catalog(tmp_path),
        executor,
        artifact_root=tmp_path / "runs",
        job_id_factory=lambda: "lab-job-cancel",
    )
    submitted = runner.submit(
        AIOpsLabBenchmarkRequest("hotel-reservation-detection-v1", repetitions=3)
    )
    assert executor.started.wait(timeout=1)

    runner.cancel(submitted.job_id)
    finished = _wait_terminal(store, submitted.job_id)

    assert finished.status is ExperimentJobStatus.CANCELLED
    assert len(executor.calls) == 0
    runner.shutdown()


def test_runner_rejects_unknown_benchmark_before_executor(tmp_path):
    store = SQLiteAIOpsLabJobStore(tmp_path / "jobs.sqlite3")
    executor = _FakeExecutor()
    runner = AIOpsLabJobRunner(
        store,
        _catalog(tmp_path),
        executor,
        artifact_root=tmp_path / "runs",
        job_id_factory=lambda: "lab-job-unknown",
    )

    submitted = runner.submit(AIOpsLabBenchmarkRequest("unknown-benchmark"))
    finished = _wait_terminal(store, submitted.job_id)

    assert finished.status is ExperimentJobStatus.BLOCKED
    assert "not registered" in finished.error
    assert executor.calls == []
    runner.shutdown()


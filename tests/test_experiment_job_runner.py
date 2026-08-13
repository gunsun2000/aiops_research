from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import monotonic, sleep

from aiops_k8s_agents.experiment_job_runner import ExperimentJobRunner
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


def _request(repetitions: int = 1) -> ExperimentRuntimeRequest:
    return ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode=ExecutionMode.MOCK,
        backend=ExecutionBackend.PYTHON,
        protocol_profile="four-agent-role-veto-v1",
        repetitions=repetitions,
    )


@dataclass
class _Result:
    experiment_id: str
    status: str

    def to_dict(self):
        return {
            "experiment_id": self.experiment_id,
            "status": self.status,
            "session": {"experiment_id": self.experiment_id},
        }


class _ImmediateRuntime:
    def __init__(self, sink, experiment_id):
        self.sink = sink
        self.experiment_id = experiment_id

    def run(self, _request):
        self.sink.emit(
            RuntimeEvent(
                experiment_id=self.experiment_id,
                sequence=1,
                stage=RuntimeStage.PREFLIGHT,
                status="running",
                message="runtime preflight",
                created_at="2026-08-03T02:00:00+00:00",
            )
        )
        return _Result(self.experiment_id, "recovered")


def _wait_for_terminal(store, experiment_id, timeout=2.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job = store.get(experiment_id)
        if job is not None and job.status.terminal:
            return job
        sleep(0.01)
    raise AssertionError("job did not become terminal")


def test_submit_returns_before_runtime_finishes_and_persists_result(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")
    release = Event()

    class BlockingRuntime(_ImmediateRuntime):
        def run(self, request):
            release.wait(timeout=2.0)
            return super().run(request)

    runner = ExperimentJobRunner(
        store,
        runtime_factory=lambda sink, _cancel, experiment_id: BlockingRuntime(
            sink, experiment_id
        ),
        experiment_id_factory=lambda: "exp-background",
    )

    started = monotonic()
    job = runner.submit(_request())
    elapsed = monotonic() - started

    assert elapsed < 0.2
    assert job.experiment_id == "exp-background"
    assert store.get(job.experiment_id).status in {
        ExperimentJobStatus.QUEUED,
        ExperimentJobStatus.RUNNING,
    }

    release.set()
    finished = _wait_for_terminal(store, job.experiment_id)
    runner.shutdown()

    assert finished.status is ExperimentJobStatus.COMPLETED
    assert finished.result["attempts"][0]["status"] == "recovered"
    assert [event.message for event in store.events_after(job.experiment_id)] == [
        "runtime preflight"
    ]


def test_repetitions_are_resequenced_under_one_job_id(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")
    runner = ExperimentJobRunner(
        store,
        runtime_factory=lambda sink, _cancel, experiment_id: _ImmediateRuntime(
            sink, experiment_id
        ),
        experiment_id_factory=lambda: "exp-repeat",
    )

    job = runner.submit(_request(repetitions=2))
    finished = _wait_for_terminal(store, job.experiment_id)
    runner.shutdown()

    events = store.events_after(job.experiment_id)
    assert [event.experiment_id for event in events] == ["exp-repeat", "exp-repeat"]
    assert [event.sequence for event in events] == [1, 2]
    assert [event.payload["attempt"] for event in events] == [1, 2]
    assert len(finished.result["attempts"]) == 2


def test_cancel_sets_runtime_signal_and_persists_cancelled_result(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")
    runtime_started = Event()
    cancellation_seen = Event()

    class CancellableRuntime:
        def __init__(self, cancel, experiment_id):
            self.cancel = cancel
            self.experiment_id = experiment_id

        def run(self, _request):
            runtime_started.set()
            assert self.cancel.wait(timeout=2.0)
            cancellation_seen.set()
            return _Result(self.experiment_id, "cancelled")

    runner = ExperimentJobRunner(
        store,
        runtime_factory=lambda _sink, cancel, experiment_id: CancellableRuntime(
            cancel, experiment_id
        ),
        experiment_id_factory=lambda: "exp-cancellable",
    )
    job = runner.submit(_request())
    assert runtime_started.wait(timeout=1.0)

    requested = runner.cancel(job.experiment_id)
    finished = _wait_for_terminal(store, job.experiment_id)
    runner.shutdown()

    assert requested.cancel_requested is True
    assert cancellation_seen.is_set()
    assert finished.status is ExperimentJobStatus.CANCELLED


def test_runner_startup_marks_stale_jobs_interrupted(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")
    store.create(_request(), experiment_id="exp-stale")

    runner = ExperimentJobRunner(
        store,
        runtime_factory=lambda sink, _cancel, experiment_id: _ImmediateRuntime(
            sink, experiment_id
        ),
    )

    assert store.get("exp-stale").status is ExperimentJobStatus.INTERRUPTED
    runner.shutdown()


def test_shutdown_cancels_running_jobs_before_waiting(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")
    runtime_started = Event()
    cancellation_seen = Event()

    class ShutdownAwareRuntime:
        def __init__(self, cancel, experiment_id):
            self.cancel = cancel
            self.experiment_id = experiment_id

        def run(self, _request):
            runtime_started.set()
            assert self.cancel.wait(timeout=2.0)
            cancellation_seen.set()
            return _Result(self.experiment_id, "cancelled")

    runner = ExperimentJobRunner(
        store,
        runtime_factory=lambda _sink, cancel, experiment_id: ShutdownAwareRuntime(
            cancel, experiment_id
        ),
        experiment_id_factory=lambda: "exp-shutdown",
    )
    job = runner.submit(_request())
    assert runtime_started.wait(timeout=1.0)

    runner.shutdown(wait=True)

    assert cancellation_seen.is_set()
    assert store.get(job.experiment_id).status is ExperimentJobStatus.CANCELLED


def test_aiopslab_detection_and_recovery_share_one_experiment_job(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")
    received_requests = []

    class IncidentAdapter:
        def prepare(self, request, *, experiment_id, repetition, cancellation, event_sink):
            assert experiment_id == "exp-unified-aiopslab"
            assert repetition == 1
            event_sink.emit(
                RuntimeEvent(
                    experiment_id=experiment_id,
                    sequence=0,
                    stage=RuntimeStage.COLLECTING_EVIDENCE,
                    status="completed",
                    message="AIOpsLab detection normalized",
                    created_at="2026-08-04T00:00:00+00:00",
                    payload={"benchmark_id": request.benchmark_id},
                )
            )
            return {
                "source": "aiopslab",
                "accuracy": "Synthetic",
                "anomaly_detected": True,
                "ttd_seconds": 0.0,
            }

    class CapturingRuntime(_ImmediateRuntime):
        def run(self, request):
            received_requests.append(request)
            return super().run(request)

    runner = ExperimentJobRunner(
        store,
        runtime_factory=lambda sink, _cancel, experiment_id: CapturingRuntime(
            sink, experiment_id
        ),
        experiment_id_factory=lambda: "exp-unified-aiopslab",
        incident_adapter=IncidentAdapter(),
    )
    request = ExperimentRuntimeRequest(
        scenario_id="aiopslab-hotel-reservation",
        namespace="test-hotel-reservation",
        deployment="geo",
        metric="availability",
        threshold=1.0,
        mode="mock",
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
        incident_source="aiopslab",
        benchmark_id="hotel-reservation-detection-v1",
    )

    job = runner.submit(request)
    finished = _wait_for_terminal(store, job.experiment_id)
    runner.shutdown()

    assert finished.experiment_id == "exp-unified-aiopslab"
    assert finished.result["incident_source"] == "aiopslab"
    assert finished.result["attempts"][0]["detection"]["source"] == "aiopslab"
    assert received_requests[0].detection_context["anomaly_detected"] is True
    assert [event.experiment_id for event in store.events_after(job.experiment_id)] == [
        "exp-unified-aiopslab",
        "exp-unified-aiopslab",
    ]


def test_safe_failure_is_persisted_as_safety_block_not_runtime_failure(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")

    class SafetyBlockedRuntime(_ImmediateRuntime):
        def run(self, request):
            result = super().run(request)
            return _Result(result.experiment_id, "safe_failure")

    runner = ExperimentJobRunner(
        store,
        runtime_factory=lambda sink, _cancel, experiment_id: SafetyBlockedRuntime(
            sink, experiment_id
        ),
        experiment_id_factory=lambda: "exp-safe-failure",
    )

    job = runner.submit(_request())
    finished = _wait_for_terminal(store, job.experiment_id)
    runner.shutdown()

    assert finished.status is ExperimentJobStatus.BLOCKED
    assert finished.result["attempts"][0]["status"] == "safe_failure"


def test_dry_run_validation_is_persisted_as_completed(tmp_path):
    store = SQLiteExperimentJobStore(tmp_path / "jobs.sqlite3")

    class DryRunRuntime(_ImmediateRuntime):
        def run(self, request):
            result = super().run(request)
            return _Result(result.experiment_id, "dry_run_validated")

    runner = ExperimentJobRunner(
        store,
        runtime_factory=lambda sink, _cancel, experiment_id: DryRunRuntime(
            sink, experiment_id
        ),
        experiment_id_factory=lambda: "exp-dry-run-validated",
    )

    job = runner.submit(_request())
    finished = _wait_for_terminal(store, job.experiment_id)
    runner.shutdown()

    assert finished.status is ExperimentJobStatus.COMPLETED
    assert finished.result["attempts"][0]["status"] == "dry_run_validated"

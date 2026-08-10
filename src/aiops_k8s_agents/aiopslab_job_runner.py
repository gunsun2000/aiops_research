from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Condition, Event, RLock, Thread
from typing import Any, Callable, Protocol

from aiops_k8s_agents.aiopslab_benchmark import (
    AIOpsLabBenchmarkCatalog,
    AIOpsLabBenchmarkSpec,
    AIOpsLabExecutionCancelled,
    AIOpsLabExecutionResult,
    sanitize_benchmark_output,
)
from aiops_k8s_agents.aiopslab_jobs import (
    AIOpsLabBenchmarkJob,
    AIOpsLabBenchmarkRequest,
    SQLiteAIOpsLabJobStore,
)
from aiops_k8s_agents.aiopslab_results import (
    summarize_aiopslab_reports,
    write_aiopslab_summary_files,
)
from aiops_k8s_agents.experiment_jobs import ExperimentJobStatus
from aiops_k8s_agents.experiment_runtime_models import RuntimeEvent, RuntimeStage


class AIOpsLabExecutor(Protocol):
    def readiness(self) -> dict[str, Any]: ...

    def execute(
        self,
        spec: AIOpsLabBenchmarkSpec,
        *,
        job_id: str,
        repetition: int,
        output_dir: str | Path,
        cancellation: Event,
    ) -> AIOpsLabExecutionResult: ...


class AIOpsLabJobRunner:
    def __init__(
        self,
        store: SQLiteAIOpsLabJobStore,
        catalog: AIOpsLabBenchmarkCatalog,
        executor: AIOpsLabExecutor,
        *,
        artifact_root: str | Path,
        job_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.executor = executor
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.job_id_factory = job_id_factory or _default_job_id
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._threads: dict[str, Thread] = {}
        self._cancellations: dict[str, Event] = {}
        self.store.interrupt_nonterminal_jobs()

    def submit(self, request: AIOpsLabBenchmarkRequest) -> AIOpsLabBenchmarkJob:
        job_id = self.job_id_factory()
        job = self.store.create(request, job_id=job_id)
        cancellation = Event()
        thread = Thread(
            target=self._run_job,
            args=(job_id, cancellation),
            name=f"aiopslab-benchmark-{job_id}",
            daemon=True,
        )
        with self._condition:
            self._cancellations[job_id] = cancellation
            self._threads[job_id] = thread
            thread.start()
            self._condition.notify_all()
        return job

    def cancel(self, job_id: str) -> AIOpsLabBenchmarkJob:
        job = self.store.request_cancel(job_id)
        with self._condition:
            cancellation = self._cancellations.get(job_id)
            if cancellation is not None:
                cancellation.set()
            self._condition.notify_all()
        return job

    def wait_for_events(
        self,
        job_id: str,
        *,
        after_sequence: int = 0,
        timeout: float = 15.0,
    ) -> tuple[RuntimeEvent, ...]:
        events = self.store.events_after(job_id, after_sequence)
        if events:
            return events
        job = self.store.get(job_id)
        if job is None or job.status.terminal:
            return ()
        with self._condition:
            self._condition.wait(timeout=max(0.0, timeout))
        return self.store.events_after(job_id, after_sequence)

    def shutdown(self, wait: bool = True) -> None:
        with self._condition:
            active = tuple(self._threads.items())
            for cancellation in self._cancellations.values():
                cancellation.set()
            self._condition.notify_all()
        for job_id, _ in active:
            try:
                self.store.request_cancel(job_id)
            except KeyError:
                pass
        if wait:
            for _, thread in active:
                thread.join(timeout=5)

    def _run_job(self, job_id: str, cancellation: Event) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        self.store.transition(job_id, ExperimentJobStatus.RUNNING)
        emitter = _BenchmarkEventEmitter(job_id, self.store, self._notify)
        terminal_status = ExperimentJobStatus.COMPLETED
        error = ""
        reports: list[str] = []
        job_dir = self.artifact_root / job_id
        reports_dir = job_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        try:
            emitter.emit(RuntimeStage.PREFLIGHT, "running", "Benchmark preflight started")
            spec = self.catalog.resolve(job.request.benchmark_id)
            spec.validate_request(job.request)
            readiness = self.executor.readiness()
            if not readiness.get("ready"):
                raise _BenchmarkBlocked("; ".join(readiness.get("reasons", [])))
            for repetition in range(1, job.request.repetitions + 1):
                if cancellation.is_set():
                    raise AIOpsLabExecutionCancelled("benchmark cancelled")
                emitter.emit(
                    RuntimeStage.ANALYZING,
                    "running",
                    f"AIOpsLab repetition {repetition}/{job.request.repetitions}",
                    payload={
                        "repetition": repetition,
                        "total_repetitions": job.request.repetitions,
                    },
                )
                execution = self.executor.execute(
                    spec,
                    job_id=job_id,
                    repetition=repetition,
                    output_dir=reports_dir,
                    cancellation=cancellation,
                )
                reports.append(str(execution.report_path))
                emitter.emit(
                    RuntimeStage.ANALYZING,
                    "completed",
                    f"AIOpsLab repetition {repetition} completed",
                    payload={
                        "repetition": repetition,
                        "report": str(execution.report_path),
                    },
                )
            result = _aggregate(job_id, reports_dir, job_dir, reports)
            emitter.emit(
                RuntimeStage.COMPLETED,
                "completed",
                "AIOpsLab benchmark completed",
                payload={"total_runs": result["total_runs"]},
            )
        except AIOpsLabExecutionCancelled as exc:
            terminal_status = ExperimentJobStatus.CANCELLED
            error = sanitize_benchmark_output(str(exc))
            result = _empty_result(job_id, job_dir, reports)
        except _BenchmarkBlocked as exc:
            terminal_status = ExperimentJobStatus.BLOCKED
            error = sanitize_benchmark_output(str(exc))
            result = _empty_result(job_id, job_dir, reports)
        except KeyError as exc:
            terminal_status = ExperimentJobStatus.BLOCKED
            error = sanitize_benchmark_output(str(exc).strip("'"))
            result = _empty_result(job_id, job_dir, reports)
        except Exception as exc:
            terminal_status = (
                ExperimentJobStatus.CANCELLED
                if cancellation.is_set()
                else ExperimentJobStatus.FAILED
            )
            error = sanitize_benchmark_output(str(exc))
            result = _empty_result(job_id, job_dir, reports)
        finally:
            if cancellation.is_set() and terminal_status is ExperimentJobStatus.COMPLETED:
                terminal_status = ExperimentJobStatus.CANCELLED
            result["status"] = terminal_status.value
            self.store.set_result(
                job_id,
                status=terminal_status,
                result=result,
                error=error,
            )
            with self._condition:
                self._threads.pop(job_id, None)
                self._cancellations.pop(job_id, None)
                self._condition.notify_all()

    def _notify(self) -> None:
        with self._condition:
            self._condition.notify_all()


class _BenchmarkEventEmitter:
    def __init__(
        self,
        job_id: str,
        store: SQLiteAIOpsLabJobStore,
        notify: Callable[[], None],
    ) -> None:
        self.job_id = job_id
        self.store = store
        self.notify = notify
        self.sequence = 0

    def emit(
        self,
        stage: RuntimeStage,
        status: str,
        message: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        self.sequence += 1
        event = RuntimeEvent(
            experiment_id=self.job_id,
            sequence=self.sequence,
            stage=stage,
            status=status,
            message=message,
            created_at=datetime.now(UTC).isoformat(),
            payload=payload or {},
        )
        self.store.append_event(event)
        self.notify()
        return event


class _BenchmarkBlocked(RuntimeError):
    pass


def _aggregate(
    job_id: str,
    reports_dir: Path,
    job_dir: Path,
    reports: list[str],
) -> dict[str, Any]:
    summary = summarize_aiopslab_reports(reports_dir)
    markdown_path = job_dir / "aiopslab_summary.md"
    csv_path = job_dir / "aiopslab_summary.csv"
    write_aiopslab_summary_files(summary, markdown_path, csv_path)
    return {
        "job_id": job_id,
        "total_runs": summary.total_runs,
        "correct_runs": summary.correct_runs,
        "metric_success_runs": summary.metric_success_runs,
        "accuracy": (
            round(summary.correct_runs / summary.total_runs, 6)
            if summary.total_runs
            else None
        ),
        "average_ttd": summary.average_ttd,
        "average_steps": summary.average_steps,
        "average_final_reward": summary.average_final_reward,
        "average_team_reward": summary.average_team_reward,
        "average_agent_rewards": summary.average_agent_rewards,
        "records": [asdict(record) for record in summary.records],
        "reports": reports,
        "artifacts": {
            "markdown": str(markdown_path),
            "csv": str(csv_path),
            "directory": str(job_dir),
        },
    }


def _empty_result(job_id: str, job_dir: Path, reports: list[str]) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "total_runs": len(reports),
        "correct_runs": 0,
        "metric_success_runs": 0,
        "accuracy": None,
        "average_ttd": None,
        "average_steps": None,
        "average_final_reward": None,
        "average_team_reward": None,
        "average_agent_rewards": {},
        "records": [],
        "reports": reports,
        "artifacts": {"directory": str(job_dir)},
    }


def _default_job_id() -> str:
    return f"lab-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"

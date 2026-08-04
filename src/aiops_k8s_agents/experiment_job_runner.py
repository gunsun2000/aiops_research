from __future__ import annotations

from dataclasses import replace
from threading import Condition, Event, RLock, Thread
from typing import Any, Callable, Mapping

from aiops_k8s_agents.experiment_jobs import (
    ExperimentJob,
    ExperimentJobStatus,
    SQLiteExperimentJobStore,
)
from aiops_k8s_agents.experiment_runtime import default_experiment_id
from aiops_k8s_agents.experiment_runtime_models import (
    ExperimentRuntimeRequest,
    RuntimeEvent,
)


RuntimeFactory = Callable[[Any, Event, str], Any]


class ExperimentJobRunner:
    """Runs bounded experiment runtimes outside the HTTP request lifecycle."""

    def __init__(
        self,
        store: SQLiteExperimentJobStore,
        runtime_factory: RuntimeFactory,
        *,
        experiment_id_factory: Callable[[], str] = default_experiment_id,
        incident_adapter: Any | None = None,
    ) -> None:
        self.store = store
        self.runtime_factory = runtime_factory
        self.experiment_id_factory = experiment_id_factory
        self.incident_adapter = incident_adapter
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._threads: dict[str, Thread] = {}
        self._cancellations: dict[str, Event] = {}
        self.store.interrupt_nonterminal_jobs()

    def submit(self, request: ExperimentRuntimeRequest) -> ExperimentJob:
        experiment_id = self.experiment_id_factory()
        job = self.store.create(request, experiment_id=experiment_id)
        cancellation = Event()
        thread = Thread(
            target=self._run_job,
            args=(experiment_id, cancellation),
            name=f"aiops-experiment-{experiment_id}",
            daemon=True,
        )
        with self._condition:
            self._cancellations[experiment_id] = cancellation
            self._threads[experiment_id] = thread
            thread.start()
            self._condition.notify_all()
        return job

    def cancel(self, experiment_id: str) -> ExperimentJob:
        job = self.store.request_cancel(experiment_id)
        with self._condition:
            cancellation = self._cancellations.get(experiment_id)
            if cancellation is not None:
                cancellation.set()
            self._condition.notify_all()
        return job

    def is_running(self, experiment_id: str) -> bool:
        with self._lock:
            thread = self._threads.get(experiment_id)
            return bool(thread and thread.is_alive())

    def wait_for_events(
        self,
        experiment_id: str,
        *,
        after_sequence: int = 0,
        timeout: float = 15.0,
    ) -> tuple[RuntimeEvent, ...]:
        events = self.store.events_after(experiment_id, after_sequence)
        if events:
            return events
        job = self.store.get(experiment_id)
        if job is None or job.status.terminal:
            return ()
        with self._condition:
            self._condition.wait(timeout=max(0.0, timeout))
        return self.store.events_after(experiment_id, after_sequence)

    def shutdown(self, wait: bool = True) -> None:
        with self._condition:
            active = tuple(
                (
                    experiment_id,
                    self._threads[experiment_id],
                    cancellation,
                )
                for experiment_id, cancellation in self._cancellations.items()
                if experiment_id in self._threads
            )
            for experiment_id, _, _ in active:
                try:
                    self.store.request_cancel(experiment_id)
                except KeyError:
                    continue
            for _, _, cancellation in active:
                cancellation.set()
            self._condition.notify_all()
        if wait:
            for _, thread, _ in active:
                thread.join(timeout=5.0)

    def _run_job(self, experiment_id: str, cancellation: Event) -> None:
        job = self.store.get(experiment_id)
        if job is None:
            return
        self.store.transition(experiment_id, ExperimentJobStatus.RUNNING)
        attempts: list[dict[str, Any]] = []
        terminal_status = ExperimentJobStatus.COMPLETED
        error = ""
        sink = _PersistentRuntimeEventSink(
            experiment_id,
            self.store,
            self._notify,
        )
        request = replace(job.request, repetitions=1)
        try:
            for attempt in range(1, job.request.repetitions + 1):
                if cancellation.is_set():
                    terminal_status = ExperimentJobStatus.CANCELLED
                    break
                sink.attempt = attempt
                attempt_id = f"{experiment_id}-r{attempt:02d}"
                attempt_request = request
                detection: dict[str, Any] = {}
                if request.incident_source == "aiopslab":
                    if self.incident_adapter is None:
                        raise RuntimeError("AIOpsLab incident adapter is unavailable")
                    detection = dict(self.incident_adapter.prepare(
                        request,
                        experiment_id=experiment_id,
                        repetition=attempt,
                        cancellation=cancellation,
                        event_sink=sink,
                    ))
                    attempt_request = replace(
                        request,
                        detection_context=detection,
                    )
                runtime = self.runtime_factory(sink, cancellation, attempt_id)
                result = runtime.run(attempt_request)
                serialized = _result_dict(result)
                if detection:
                    serialized["detection"] = detection
                attempts.append(serialized)
                result_status = str(serialized.get("status", "failed"))
                mapped = _job_status(result_status)
                if mapped is ExperimentJobStatus.CANCELLED:
                    terminal_status = mapped
                    break
                if mapped is ExperimentJobStatus.BLOCKED:
                    terminal_status = mapped
                elif mapped is ExperimentJobStatus.FAILED:
                    terminal_status = mapped
        except Exception as exc:
            terminal_status = (
                ExperimentJobStatus.CANCELLED
                if cancellation.is_set()
                else ExperimentJobStatus.FAILED
            )
            error = str(exc)
        finally:
            if cancellation.is_set() and terminal_status is ExperimentJobStatus.COMPLETED:
                terminal_status = ExperimentJobStatus.CANCELLED
            aggregate = {
                "experiment_id": experiment_id,
                "status": terminal_status.value,
                "incident_source": job.request.incident_source,
                "benchmark_id": job.request.benchmark_id,
                "attempts": attempts,
                "successful_attempts": sum(
                    1 for attempt in attempts if _job_status(str(attempt.get("status")))
                    is ExperimentJobStatus.COMPLETED
                ),
                "failed_attempts": sum(
                    1 for attempt in attempts if _job_status(str(attempt.get("status")))
                    in {ExperimentJobStatus.FAILED, ExperimentJobStatus.BLOCKED}
                ),
            }
            self.store.set_result(
                experiment_id,
                status=terminal_status,
                result=aggregate,
                error=error,
            )
            with self._condition:
                self._threads.pop(experiment_id, None)
                self._cancellations.pop(experiment_id, None)
                self._condition.notify_all()

    def _notify(self) -> None:
        with self._condition:
            self._condition.notify_all()


class _PersistentRuntimeEventSink:
    def __init__(
        self,
        experiment_id: str,
        store: SQLiteExperimentJobStore,
        notify: Callable[[], None],
    ) -> None:
        self.experiment_id = experiment_id
        self.store = store
        self.notify = notify
        self.attempt = 1
        self._sequence = 0

    def emit(self, event: RuntimeEvent) -> None:
        self._sequence += 1
        payload = dict(event.payload)
        payload.update({
            "attempt": self.attempt,
            "runtime_experiment_id": event.experiment_id,
        })
        persisted = RuntimeEvent(
            experiment_id=self.experiment_id,
            sequence=self._sequence,
            stage=event.stage,
            status=event.status,
            message=event.message,
            created_at=event.created_at,
            payload=payload,
        )
        self.store.append_event(persisted)
        self.notify()


def _result_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        value = result.to_dict()
    elif isinstance(result, Mapping):
        value = dict(result)
    else:
        raise TypeError("runtime result must provide to_dict or be a mapping")
    if not isinstance(value, Mapping):
        raise TypeError("runtime result serialization must be a mapping")
    return dict(value)


def _job_status(runtime_status: str) -> ExperimentJobStatus:
    normalized = runtime_status.strip().lower()
    if normalized in {
        "completed",
        "recovered",
        "recovered_after_replan",
        "no_action_required",
    }:
        return ExperimentJobStatus.COMPLETED
    if normalized in {"cancelled", "cancelling"}:
        return ExperimentJobStatus.CANCELLED
    if normalized in {
        "blocked",
        "safe_failure",
        "safe_stopped",
        "consensus_rejected",
        "configuration_rejected",
    }:
        return ExperimentJobStatus.BLOCKED
    if normalized == "interrupted":
        return ExperimentJobStatus.INTERRUPTED
    return ExperimentJobStatus.FAILED

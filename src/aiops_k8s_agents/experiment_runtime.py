from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from aiops_k8s_agents.experiment_runtime_models import (
    ExperimentRuntimeRequest,
    ExperimentRuntimeResult,
    RuntimeEvent,
    RuntimeStage,
)
from aiops_k8s_agents.experiment_session import normalize_experiment_session
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.mutual_supervision_models import to_serializable
from aiops_k8s_agents.operation_lock import TargetOperationLock
from aiops_k8s_agents.real_evidence import RuntimeConfiguration


class RuntimeEventSink(Protocol):
    def emit(self, event: RuntimeEvent) -> None: ...


class RuntimeExecutionError(RuntimeError):
    """Raised when a runtime lifecycle cannot produce a valid report."""


STREAM_STAGE = {
    "evidence": RuntimeStage.COLLECTING_EVIDENCE,
    "initial_decisions": RuntimeStage.AGENT_REASONING,
    "peer_reviews": RuntimeStage.NEGOTIATING,
    "negotiation_rounds": RuntimeStage.NEGOTIATING,
    "safety_validations": RuntimeStage.VALIDATING,
    "executed_actions": RuntimeStage.EXECUTING,
    "post_execution_reviews": RuntimeStage.OBSERVING_RECOVERY,
}


def default_experiment_id() -> str:
    return f"exp-{uuid4().hex}"


@dataclass
class RuntimeResearchEventBridge:
    experiment_id: str
    event_sink: RuntimeEventSink
    artifact_store: Any | None = None
    _sequence: int = field(default=0, init=False, repr=False)
    _events: list[RuntimeEvent] = field(default_factory=list, init=False, repr=False)

    def append(self, stream: str, event: Any) -> None:
        persisted = deepcopy(to_serializable(event))
        if isinstance(persisted, dict):
            persisted["run_id"] = self.experiment_id
        if self.artifact_store is not None:
            self.artifact_store.append(stream, persisted)
        stage = STREAM_STAGE.get(stream)
        if stage is not None:
            self.emit(stage, f"research event: {stream}", {"stream": stream, "event": persisted})

    def finalize(self, report: dict[str, Any]) -> dict[str, str]:
        finalized = deepcopy(report)
        finalized["run_id"] = self.experiment_id
        if self.artifact_store is None:
            return {}
        return dict(self.artifact_store.finalize(finalized) or {})

    def emit(self, stage: RuntimeStage, message: str, payload: Mapping[str, Any] | None = None) -> None:
        self._sequence += 1
        event = RuntimeEvent(
                experiment_id=self.experiment_id,
                sequence=self._sequence,
                stage=stage,
                status="running",
                message=message,
                created_at=datetime.now(UTC).isoformat(),
                payload=deepcopy(dict(payload or {})),
            )
        self._events.append(event)
        self.event_sink.emit(event)


@dataclass
class ExperimentRuntime:
    configuration: RuntimeConfiguration
    chaos: Any
    coordinator_factory: Callable[[ExperimentRuntimeRequest], Any]
    event_sink: RuntimeEventSink
    experiment_id_factory: Callable[[], str] = default_experiment_id
    artifact_event_store: Any | None = None
    cancellation_event: Event | None = None
    lock_dir: str | None = None

    def run(self, request: ExperimentRuntimeRequest) -> ExperimentRuntimeResult:
        experiment_id = self.experiment_id_factory()
        bridge = RuntimeResearchEventBridge(experiment_id, self.event_sink, self.artifact_event_store)
        report: dict[str, Any] = self._base_report(experiment_id, request)
        application: Any | None = None
        cleanup: Mapping[str, Any] = {}
        primary_status = "failed"

        try:
            self._validate_request(request)
            if self._cancelled():
                return self._finish(request, report, "cancelled", {}, bridge)
            bridge.emit(RuntimeStage.PREFLIGHT, "runtime preflight")

            lock_context = (
                TargetOperationLock(request.namespace, request.deployment, self.lock_dir)
                if request.mode == ExecutionMode.REAL
                else _null_context()
            )
            with lock_context:
                if request.mode == ExecutionMode.REAL:
                    preflight = self.chaos.preflight()
                    if not bool(getattr(preflight, "valid", False)):
                        report["error"] = getattr(preflight, "stderr", "chaos preflight failed")
                        primary_status = "blocked"
                        report["final_status"] = primary_status
                        return self._finish(request, report, primary_status, {}, bridge)
                    bridge.emit(RuntimeStage.INJECTING_FAULT, "injecting registered fault")
                    application = self.chaos.inject(request.scenario_id)
                    if not bool(getattr(application, "valid", False)):
                        report["error"] = getattr(application, "stderr", "fault injection failed")
                        raise RuntimeExecutionError(report["error"])

            bridge.emit(RuntimeStage.COLLECTING_EVIDENCE, "collecting registered evidence")
            bridge.emit(RuntimeStage.AGENT_REASONING, "running mutual supervision")
            coordinator = self.coordinator_factory(request)
            if hasattr(coordinator, "event_store"):
                store = self.artifact_event_store or getattr(coordinator, "event_store", None)
                bridge.artifact_store = store
                coordinator.event_store = bridge
            report = deepcopy(coordinator.run(
                request.namespace, request.deployment, request.metric, request.threshold
            ))
            report["run_id"] = experiment_id
            report["mode"] = request.mode.value
            artifacts = bridge.finalize(report)
            if artifacts:
                report["artifacts"] = artifacts
            primary_status = str(report.get("final_status", "failed"))
            for stage, key in (
                (RuntimeStage.VALIDATING, "safety_validation"),
                (RuntimeStage.EXECUTING, "execution_result"),
                (RuntimeStage.OBSERVING_RECOVERY, "recovery_monitoring"),
            ):
                if report.get(key):
                    bridge.emit(stage, f"runtime stage: {key}")
            if self._cancelled():
                primary_status = "cancelled"
                report["final_status"] = primary_status
        except _BlockedRequest as exc:
            primary_status = "blocked"
            report["error"] = str(exc)
            report["final_status"] = primary_status
        except (TimeoutError, InterruptedError) as exc:
            primary_status = "interrupted"
            report["error"] = str(exc)
            report["final_status"] = primary_status
        except Exception as exc:
            primary_status = "failed"
            report["error"] = str(exc)
            report["final_status"] = primary_status
        finally:
            if application is not None:
                bridge.emit(RuntimeStage.CLEANUP, "cleaning up registered fault")
                try:
                    cleanup = _mapping(self.chaos.cleanup(application))
                    if cleanup.get("valid") is not True:
                        report["cleanup_error"] = str(cleanup.get("stderr", "cleanup failed"))
                        report["human_review_required"] = True
                except Exception as exc:
                    cleanup = {"valid": False, "stderr": str(exc)}
                    report["cleanup_error"] = str(exc)
                    report["human_review_required"] = True

        if report.get("cleanup_error"):
            report["cleanup_status"] = "cleanup_failed"
        status = str(report.get("final_status", primary_status))
        return self._finish(request, report, status, cleanup, bridge)

    def _finish(
        self,
        request: ExperimentRuntimeRequest,
        report: dict[str, Any],
        status: str,
        cleanup: Mapping[str, Any],
        bridge: RuntimeResearchEventBridge,
    ) -> ExperimentRuntimeResult:
        report = deepcopy(report)
        report.update({"run_id": bridge.experiment_id, "mode": request.mode.value, "final_status": status})
        bridge.emit(RuntimeStage.COMPLETED, f"experiment {status}")
        session = normalize_experiment_session(report)
        events = tuple(bridge._events)
        return ExperimentRuntimeResult(bridge.experiment_id, status, report, session, events, cleanup)

    def _validate_request(self, request: ExperimentRuntimeRequest) -> None:
        if request.namespace not in self.configuration.allowed_namespaces:
            raise _BlockedRequest(f"namespace is not allowlisted: {request.namespace}")
        if request.deployment not in self.configuration.allowed_deployments:
            raise _BlockedRequest(f"deployment is not allowlisted: {request.deployment}")
        if request.scenario_id not in self.configuration.scenarios:
            raise _BlockedRequest(f"scenario is not registered: {request.scenario_id}")
        if request.metric not in self.configuration.metric_queries:
            raise _BlockedRequest(f"metric is not registered: {request.metric}")

    def _cancelled(self) -> bool:
        return self.cancellation_event is not None and self.cancellation_event.is_set()

    @staticmethod
    def _base_report(experiment_id: str, request: ExperimentRuntimeRequest) -> dict[str, Any]:
        return {
            "run_id": experiment_id,
            "mode": request.mode.value,
            "final_status": "failed",
            "evidence": {},
            "diagnosis": {},
            "negotiation": {},
            "safety_validation": {},
            "execution_result": {},
            "recovery_monitoring": {},
            "human_review_required": False,
        }


class _BlockedRequest(ValueError):
    pass


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {"valid": False, "stderr": "invalid cleanup result"}

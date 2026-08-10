from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
import os
from time import monotonic
import time
from threading import Event
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from aiops_k8s_agents.experiment_runtime_models import (
    ExperimentRuntimeRequest,
    ExperimentRuntimeResult,
    RuntimeEvent,
    RuntimeStage,
)
from aiops_k8s_agents.action_policy import (
    ContextualBanditPolicy,
    PolicyContext,
    cause_for_metric,
    load_policy_samples,
)
from aiops_k8s_agents.agent_adapters import (
    AgentAdapterRegistry,
    DeterministicApplicationAdapter,
    DeterministicCostAdapter,
    DeterministicHAAdapter,
    DeterministicInfrastructureAdapter,
)
from aiops_k8s_agents.experiment_session import (
    ExperimentSessionStore,
    normalize_experiment_session,
)
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.mutual_supervision_models import to_serializable
from aiops_k8s_agents.operation_lock import OperationLockError, TargetOperationLock
from aiops_k8s_agents.real_evidence import RuntimeConfiguration
from aiops_k8s_agents.recovery_evaluator import attach_recovery_evaluation


@dataclass(frozen=True)
class CoordinatorAdmission:
    executor_timeout_seconds: float
    evidence_timeout_seconds: float
    stage_timeouts: Mapping[str, float]


class CoordinatorAdmissionValidator:
    """Admit only the exact registered deterministic production coordinator."""

    def validate(
        self,
        coordinator: Any,
        request: ExperimentRuntimeRequest,
        configuration: RuntimeConfiguration,
    ) -> CoordinatorAdmission:
        from aiops_k8s_agents.kubernetes_status import collect_kubernetes_snapshot
        from aiops_k8s_agents.autogen_groupchat import (
            AUTOGEN_IMPLEMENTATION_IDS,
            AutoGenProtocolAdapter,
        )
        from aiops_k8s_agents.mutual_supervision import MutualSupervisionCoordinator
        from aiops_k8s_agents.prometheus import PrometheusAdapter
        from aiops_k8s_agents.real_evidence import PrometheusKubernetesEvidenceProvider
        from aiops_k8s_agents.recovery_monitor import KubernetesSnapshotRecoveryMonitor

        if type(coordinator) is not MutualSupervisionCoordinator:
            raise _BlockedRequest(
                "coordinator must be the registered MutualSupervisionCoordinator"
            )
        for name in ("run", "_operation_context", "_check_runtime_control"):
            if getattr(type(coordinator), name) is not getattr(MutualSupervisionCoordinator, name):
                raise _BlockedRequest(f"coordinator stage is overridden: {name}")
        if coordinator.mode != request.mode or coordinator.backend.value != request.backend.value:
            raise _BlockedRequest("coordinator mode/backend does not match request")

        evidence = coordinator.evidence_provider
        if type(evidence) is not PrometheusKubernetesEvidenceProvider:
            raise _BlockedRequest("evidence provider is not the registered production provider")
        if type(evidence.prometheus) is not PrometheusAdapter or evidence.prometheus.fetcher is not None:
            raise _BlockedRequest("Prometheus provider does not use the bounded production client")
        if evidence.kubernetes_collector is not collect_kubernetes_snapshot:
            raise _BlockedRequest("Kubernetes evidence collector is unsupported")

        monitor = coordinator.recovery_monitor
        if type(monitor) is not KubernetesSnapshotRecoveryMonitor:
            raise _BlockedRequest("recovery monitor is unsupported")
        if monitor.evidence_provider is not evidence or monitor.sleeper is not time.sleep:
            raise _BlockedRequest("recovery monitor is not the bounded production monitor")
        if monitor.max_attempts * monitor.interval_seconds > configuration.timeouts["recovery_seconds"]:
            raise _BlockedRequest("recovery monitor exceeds the registered recovery deadline")

        if type(coordinator.adapter_registry) is not AgentAdapterRegistry:
            raise _BlockedRequest("agent registry is unsupported")
        deterministic_implementations = {
            "deterministic-ha",
            "deterministic-application",
            "deterministic-infrastructure",
            "deterministic-cost",
        }
        expected_implementations = (
            deterministic_implementations | set(AUTOGEN_IMPLEMENTATION_IDS.values())
            if request.controller == "autogen"
            else deterministic_implementations
        )
        if set(coordinator.adapter_registry.factories) != expected_implementations:
            raise _BlockedRequest("agent registry is not the registered runtime registry")
        expected_adapters = (
            (
                AutoGenProtocolAdapter,
                AutoGenProtocolAdapter,
                AutoGenProtocolAdapter,
                AutoGenProtocolAdapter,
            )
            if request.controller == "autogen"
            else (
                DeterministicHAAdapter,
                DeterministicApplicationAdapter,
                DeterministicInfrastructureAdapter,
                DeterministicCostAdapter,
            )
        )
        if tuple(type(adapter) for adapter in coordinator.adapters.values()) != expected_adapters:
            raise _BlockedRequest("agent stage is unsupported or overridden")
        expected_profile = (
            "four-agent-autogen-v1"
            if request.controller == "autogen"
            else "four-agent-role-veto-v1"
        )
        if coordinator.protocol.profile_id != expected_profile:
            raise _BlockedRequest("protocol profile is not registered for the controller")

        stage_timeouts = {
            key: _positive_timeout(configuration.timeouts, key)
            for key in (
                "preflight_seconds",
                "fault_ready_seconds",
                "recovery_seconds",
                "cleanup_seconds",
            )
        }
        return CoordinatorAdmission(
            executor_timeout_seconds=15.0,
            evidence_timeout_seconds=10.0,
            stage_timeouts=stage_timeouts,
        )


class RuntimeEventSink(Protocol):
    def emit(self, event: RuntimeEvent) -> None: ...


class RuntimeExecutionError(RuntimeError):
    """Raised when a runtime lifecycle cannot produce a valid report."""


@dataclass(frozen=True)
class RuntimePreflightResult:
    """Read-only admission result produced before any runtime mutation."""

    valid: bool
    scenario_id: str
    manifest: str
    resource_kind: str | None = None
    missing_prerequisites: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "scenario_id": self.scenario_id,
            "manifest": self.manifest,
            "resource_kind": self.resource_kind,
            "missing_prerequisites": list(self.missing_prerequisites),
        }


class RuntimeCancelled(RuntimeError):
    """Raised when a runtime cancellation checkpoint is reached."""


@dataclass(frozen=True)
class RuntimeControl:
    cancellation_event: Event | None
    deadline: float | None
    clock: Callable[[], float]

    def check(self) -> None:
        if (
            self.cancellation_event is not None
            and self.cancellation_event.is_set()
        ):
            raise RuntimeCancelled("experiment cancelled")
        if self.deadline is not None and self.clock() >= self.deadline:
            raise TimeoutError("experiment runtime deadline exceeded")

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
    defer_finalization: bool = True
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
    session_store: ExperimentSessionStore | None = None
    clock: Callable[[], float] = monotonic
    admission_validator: Any | None = None

    def preflight(self, request: ExperimentRuntimeRequest) -> RuntimePreflightResult:
        """Validate one registered request without acquiring locks or mutating state."""
        self._validate_request(request)
        scenario = self.configuration.scenarios[request.scenario_id]
        manifest = str(getattr(scenario, "manifest", ""))
        if request.mode != ExecutionMode.REAL:
            return RuntimePreflightResult(True, request.scenario_id, manifest)

        resource_kind = "AIOpsLabDetection" if request.incident_source == "aiopslab" else None
        if request.incident_source == "chaos_mesh":
            try:
                checker = getattr(self.chaos, "preflight_scenario", None)
                chaos_result = (
                    checker(request.scenario_id)
                    if callable(checker)
                    else self.chaos.preflight()
                )
            except Exception:
                return RuntimePreflightResult(
                    False,
                    request.scenario_id,
                    manifest,
                    missing_prerequisites=(f"chaos_mesh:{request.scenario_id}",),
                )

            resource_kind = getattr(chaos_result, "resource_kind", None)
            if not bool(getattr(chaos_result, "valid", False)):
                missing = tuple(getattr(chaos_result, "missing_prerequisites", ()) or ())
                if not missing:
                    missing = (f"chaos_mesh:{request.scenario_id}",)
                return RuntimePreflightResult(
                    False,
                    request.scenario_id,
                    manifest,
                    resource_kind=resource_kind,
                    missing_prerequisites=missing,
                )

        try:
            coordinator = self.coordinator_factory(request)
            admission = (
                self.admission_validator or CoordinatorAdmissionValidator()
            ).validate(coordinator, request, self.configuration)
            self._validate_coordinator_mode(coordinator, request)
            if admission is None:
                raise _BlockedRequest("runtime admission is unavailable")
        except Exception:
            return RuntimePreflightResult(
                False,
                request.scenario_id,
                manifest,
                resource_kind=resource_kind,
                missing_prerequisites=("runtime.coordinator",),
            )
        return RuntimePreflightResult(
            True,
            request.scenario_id,
            manifest,
            resource_kind=resource_kind,
        )

    def run(self, request: ExperimentRuntimeRequest) -> ExperimentRuntimeResult:
        experiment_id = self.experiment_id_factory()
        bridge = RuntimeResearchEventBridge(experiment_id, self.event_sink, self.artifact_event_store)
        report: dict[str, Any] = self._base_report(experiment_id, request)
        _attach_action_policy_advice(report, request)
        application: Any | None = None
        cleanup: Mapping[str, Any] = {}
        primary_status = "failed"
        deadline = self.clock() + self.configuration.experiment_seconds
        control = RuntimeControl(self.cancellation_event, deadline, self.clock)
        lock_context = (
            TargetOperationLock(request.namespace, request.deployment, self.lock_dir)
            if request.mode == ExecutionMode.REAL
            else _null_context()
        )
        lock_acquired = False

        try:
            self._validate_request(request)
            coordinator = self.coordinator_factory(request)
            admission = (
                self.admission_validator or CoordinatorAdmissionValidator()
            ).validate(coordinator, request, self.configuration)
            self._validate_coordinator_mode(coordinator, request)
            coordinator.runtime_control = control
            coordinator.admitted_stage_timeouts = admission.stage_timeouts
            if hasattr(coordinator, "operation_lock_owned_externally"):
                coordinator.operation_lock_owned_externally = True
            control.check()
            lock_context.__enter__()
            lock_acquired = True
            bridge.emit(RuntimeStage.PREFLIGHT, "runtime preflight")
            if (
                request.mode == ExecutionMode.REAL
                and request.incident_source == "chaos_mesh"
            ):
                control.check()
                preflight = self.chaos.preflight()
                if not bool(getattr(preflight, "valid", False)):
                    raise _BlockedRequest(getattr(preflight, "stderr", "chaos preflight failed"))
                control.check()
                bridge.emit(RuntimeStage.INJECTING_FAULT, "injecting registered fault")
                control.check()
                application = self.chaos.inject(request.scenario_id)
                if not bool(getattr(application, "valid", False)):
                    raise RuntimeExecutionError(
                        getattr(application, "stderr", "fault injection failed")
                    )
                control.check()
            control.check()
            bridge.emit(RuntimeStage.COLLECTING_EVIDENCE, "collecting registered evidence")
            bridge.emit(RuntimeStage.AGENT_REASONING, "running mutual supervision")
            if hasattr(coordinator, "event_store"):
                store = self.artifact_event_store or getattr(coordinator, "event_store", None)
                bridge.artifact_store = store
                coordinator.event_store = bridge
            report = deepcopy(coordinator.run(
                request.namespace,
                request.deployment,
                request.metric,
                request.threshold,
            ))
            control.check()
            report["run_id"] = experiment_id
            report["mode"] = request.mode.value
            report["controller"] = request.controller
            report["model"] = request.model
            report["incident_source"] = request.incident_source
            report["benchmark_id"] = request.benchmark_id
            report["detection"] = deepcopy(dict(request.detection_context))
            transcript = _coordinator_transcript(coordinator)
            if transcript:
                report["autogen_transcript"] = transcript
            primary_status = str(report.get("final_status", "failed"))
            for stage, key in (
                (RuntimeStage.VALIDATING, "safety_validation"),
                (RuntimeStage.EXECUTING, "execution_result"),
                (RuntimeStage.OBSERVING_RECOVERY, "recovery_monitoring"),
            ):
                if report.get(key):
                    bridge.emit(stage, f"runtime stage: {key}")
            report["final_status"] = primary_status
        except (OperationLockError, _BlockedRequest) as exc:
            primary_status = "blocked"
            report["error"] = str(exc)
            report["final_status"] = primary_status
        except RuntimeCancelled as exc:
            primary_status = "cancelled"
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
            if lock_acquired:
                lock_context.__exit__(None, None, None)

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
        report.update({
            "run_id": bridge.experiment_id,
            "mode": request.mode.value,
            "controller": request.controller,
            "model": request.model,
            "incident_source": request.incident_source,
            "benchmark_id": request.benchmark_id,
            "detection": deepcopy(dict(request.detection_context)),
            "final_status": status,
            "cleanup": deepcopy(dict(cleanup)),
        })
        if request.incident_source == "chaos_mesh":
            bridge.emit(
                RuntimeStage.ANALYZING,
                "evaluating recovery outcome with RecoveryEvaluatorAgent",
            )
            attach_recovery_evaluation(report)
        bridge.emit(RuntimeStage.COMPLETED, f"experiment {status}")
        report["runtime_events"] = [event.to_dict() for event in bridge._events]
        if bridge.artifact_store is not None and hasattr(bridge.artifact_store, "paths"):
            report["artifacts"] = deepcopy(bridge.artifact_store.paths)
        bridge.finalize(report)
        session = normalize_experiment_session(report)
        if self.session_store is not None:
            self.session_store.put(session)
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
        scenario = self.configuration.scenarios[request.scenario_id]
        if request.incident_source != scenario.incident_source:
            raise _BlockedRequest(
                f"request incident source does not match scenario {request.scenario_id}"
            )
        if request.benchmark_id != scenario.benchmark_id:
            raise _BlockedRequest(
                f"request benchmark does not match scenario {request.scenario_id}"
            )
        for field in ("namespace", "deployment", "metric", "threshold"):
            expected = getattr(scenario, field, None)
            if expected is None:
                raise _BlockedRequest(
                    f"scenario binding is incomplete: {request.scenario_id}.{field}"
                )
            actual = getattr(request, field)
            if actual != expected:
                raise _BlockedRequest(
                    f"request {field} does not match scenario {request.scenario_id}"
                )

    @staticmethod
    def _validate_coordinator_mode(coordinator: Any, request: ExperimentRuntimeRequest) -> None:
        coordinator_mode = getattr(coordinator, "mode", None)
        if coordinator_mode is None:
            raise _BlockedRequest("coordinator mode is required")
        try:
            coordinator_mode = ExecutionMode(coordinator_mode)
        except (TypeError, ValueError) as exc:
            raise _BlockedRequest("coordinator mode is invalid") from exc
        if coordinator_mode != request.mode:
            raise _BlockedRequest(
                f"coordinator mode {coordinator_mode.value} does not match request mode {request.mode.value}"
            )
        coordinator_backend = getattr(coordinator, "backend", None)
        if coordinator_backend is not None and str(coordinator_backend) != str(request.backend):
            raise _BlockedRequest("coordinator backend does not match request backend")

    @staticmethod
    def _base_report(experiment_id: str, request: ExperimentRuntimeRequest) -> dict[str, Any]:
        return {
            "run_id": experiment_id,
            "mode": request.mode.value,
            "controller": request.controller,
            "model": request.model,
            "incident_source": request.incident_source,
            "benchmark_id": request.benchmark_id,
            "detection": deepcopy(dict(request.detection_context)),
            "action_policy": str(
                request.detection_context.get("action_policy", "baseline")
            ),
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


def _attach_action_policy_advice(
    report: dict[str, Any],
    request: ExperimentRuntimeRequest,
) -> None:
    """Attach advisory policy output without changing the bounded executor path."""

    requested_mode = str(
        request.detection_context.get("action_policy", "baseline")
    ).strip().lower()
    policy_mode = requested_mode if requested_mode in {"baseline", "learned"} else "baseline"
    policy = ContextualBanditPolicy(mode=policy_mode)
    samples_path = os.environ.get("AIOPS_ACTION_POLICY_SAMPLES", "").strip()
    if policy_mode == "learned" and samples_path:
        try:
            policy.fit(load_policy_samples(samples_path))
        except (OSError, ValueError) as exc:
            report["action_policy_error"] = str(exc)
    recommendation = policy.recommend(
        PolicyContext(
            scenario=request.scenario_id,
            metric=request.metric,
            cause=cause_for_metric(request.metric),
        )
    )
    report["action_policy"] = policy_mode
    report["action_policy_samples"] = samples_path
    report["action_policy_recommendation"] = recommendation.to_dict()


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {"valid": False, "stderr": "invalid cleanup result"}


def _coordinator_transcript(coordinator: Any) -> list[str]:
    for adapter in getattr(coordinator, "adapters", {}).values():
        lines = getattr(adapter, "transcript_lines", ())
        if lines:
            return [str(line) for line in lines]
    return []


def _positive_timeout(timeouts: Mapping[str, Any], key: str) -> float:
    value = timeouts.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _BlockedRequest(f"registered timeout is missing or invalid: {key}")
    if not isfinite(value) or value <= 0:
        raise _BlockedRequest(f"registered timeout is missing or invalid: {key}")
    return float(value)

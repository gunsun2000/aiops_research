from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from aiops_k8s_agents.experiment_runtime import ExperimentRuntime
from aiops_k8s_agents.experiment_runtime import (
    CoordinatorAdmission,
    CoordinatorAdmissionValidator,
)
from aiops_k8s_agents.experiment_runtime_models import (
    CoordinatorRuntimeCapabilities,
    ExperimentRuntimeRequest,
    RuntimeStage,
)
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.agent_adapters import build_default_agent_adapter_registry
from aiops_k8s_agents.evidence import FakeEvidenceProvider
from aiops_k8s_agents.mutual_supervision import MutualSupervisionCoordinator
from aiops_k8s_agents.prometheus import PrometheusAdapter
from aiops_k8s_agents.real_evidence import (
    MetricQueryDefinition,
    PrometheusKubernetesEvidenceProvider,
    RuntimeConfiguration,
    load_runtime_configuration,
)
from aiops_k8s_agents.recovery_monitor import KubernetesSnapshotRecoveryMonitor
from aiops_k8s_agents.research_protocol import load_research_protocol
from aiops_k8s_agents.validator import CommandValidator
from aiops_k8s_agents.research_event_store import InMemoryResearchEventStore
from aiops_k8s_agents.experiment_session import InMemoryExperimentSessionStore


class RecordingEventSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class TestAdmissionValidator:
    def validate(self, coordinator, request, configuration):
        del coordinator, request, configuration
        return CoordinatorAdmission(
            executor_timeout_seconds=15.0,
            evidence_timeout_seconds=10.0,
            stage_timeouts={},
        )


class FakeChaosAdapter:
    def __init__(self, cleanup_result=None):
        self.calls = []
        self.cleanup_result = cleanup_result or {"valid": True, "stderr": ""}

    def preflight(self):
        self.calls.append("preflight")
        return SimpleNamespace(valid=True, stderr="")

    def inject(self, scenario_id):
        self.calls.append(f"inject:{scenario_id}")
        return SimpleNamespace(scenario_id=scenario_id, valid=True, stderr="")

    def cleanup(self, application):
        self.calls.append(f"cleanup:{application.scenario_id}")
        return self.cleanup_result


class FakeCoordinator:
    runtime_capabilities = CoordinatorRuntimeCapabilities()

    def __init__(self, report, mode=ExecutionMode.REAL):
        self.report = report
        self.mode = mode

    def run(self, namespace, deployment, metric, threshold):
        return dict(self.report)


class RaisingCoordinator:
    mode = ExecutionMode.REAL
    runtime_capabilities = CoordinatorRuntimeCapabilities()

    def run(self, namespace, deployment, metric, threshold):
        raise RuntimeError("coordinator failed")


class TimeoutCoordinator:
    mode = ExecutionMode.REAL
    runtime_capabilities = CoordinatorRuntimeCapabilities()

    def run(self, namespace, deployment, metric, threshold):
        raise TimeoutError("coordinator timed out")


def approved_report(run_id):
    return {
        "run_id": run_id,
        "mode": "real",
        "final_status": "recovered",
        "active_agents": ["HA", "Application", "Infrastructure", "Cost"],
        "evidence": {
            "scenario": "cpu-stress",
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "metric_values": {"cpu": 95.0},
            "source": "prometheus+kubernetes",
        },
        "diagnosis": {"cause": "cpu_saturation"},
        "negotiation": {"consensus": "approved"},
        "safety_validation": {"valid": True},
        "execution_result": {"valid": True, "mode": "real"},
        "recovery_monitoring": {"recovery_success": True},
    }


def runtime_configuration():
    return RuntimeConfiguration(
        version="1.0.0",
        allowed_namespaces=("online-boutique", "observability"),
        allowed_deployments=("paymentservice", "checkoutservice"),
        min_replicas=1,
        max_replicas=5,
        timeouts={
            "experiment": 30,
            "preflight_seconds": 15,
            "fault_ready_seconds": 60,
            "recovery_seconds": 120,
            "cleanup_seconds": 60,
        },
        metric_queries={
            "cpu": MetricQueryDefinition("cpu", "up"),
            "memory": MetricQueryDefinition("memory", "up"),
        },
        scenarios={
            "cpu-stress": {
                "id": "cpu-stress",
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "metric": "cpu",
                "threshold": 80.0,
                "manifest": "paymentservice-cpu-stress.yaml",
            }
        },
    )


def real_request():
    return ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode="real",
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
    )


def mock_request():
    return replace(real_request(), mode=ExecutionMode.MOCK)


def runtime_with(coordinator=None, chaos=None, **kwargs):
    events = kwargs.pop("event_sink", RecordingEventSink())
    admission_validator = kwargs.pop("admission_validator", TestAdmissionValidator())
    if coordinator is None:
        coordinator_factory = lambda request: FakeCoordinator(
            approved_report("exp-runtime-1"), mode=request.mode
        )
    else:
        coordinator_factory = lambda _request: coordinator
    return ExperimentRuntime(
        configuration=runtime_configuration(),
        chaos=chaos or FakeChaosAdapter(),
        coordinator_factory=coordinator_factory,
        event_sink=events,
        experiment_id_factory=lambda: "exp-runtime-1",
        admission_validator=admission_validator,
        **kwargs,
    )


def test_runtime_runs_fault_agent_cleanup_as_one_experiment():
    events = RecordingEventSink()
    chaos = FakeChaosAdapter()
    runtime = runtime_with(
        chaos=chaos,
        event_sink=events,
    )

    result = runtime.run(real_request())

    assert result.experiment_id == "exp-runtime-1"
    assert result.status == "recovered"
    assert result.report["run_id"] == result.experiment_id
    assert chaos.calls == ["preflight", "inject:cpu-stress", "cleanup:cpu-stress"]
    assert [event.stage.value for event in result.events] == [
        "preflight", "injecting_fault", "collecting_evidence", "agent_reasoning",
        "validating", "executing", "observing_recovery", "cleanup", "analyzing", "completed",
    ]
    assert {event.experiment_id for event in result.events} == {result.experiment_id}
    assert {stage["experiment_id"] for stage in result.session.stages.values()} == {
        result.experiment_id
    }


def test_runtime_persists_recovery_evaluation_after_report_is_complete():
    result = runtime_with().run(real_request())

    evaluation = result.report["evaluation"]
    assert evaluation["evaluator"] == "RecoveryEvaluatorAgent"
    assert 0.0 < evaluation["team_reward"] <= 1.0
    assert set(evaluation["agent_rewards"]) == {
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    }
    assert result.session.stages["result"]["payload"]["evaluation"] == evaluation
    assert result.session.stages["evaluation"]["payload"] == evaluation


def test_runtime_cleans_up_fault_when_coordinator_raises():
    chaos = FakeChaosAdapter()
    result = runtime_with(coordinator=RaisingCoordinator(), chaos=chaos).run(real_request())
    assert result.status == "failed"
    assert "cleanup:cpu-stress" in chaos.calls
    assert result.cleanup["valid"] is True
    assert "coordinator failed" in result.report["error"]


def test_runtime_does_not_inject_fault_for_mock_mode():
    chaos = FakeChaosAdapter()
    result = runtime_with(chaos=chaos).run(mock_request())
    assert chaos.calls == []
    assert result.session.mode == "mock"


def test_real_aiopslab_detection_flows_to_agents_without_duplicate_chaos_injection():
    base = runtime_configuration()
    configuration = RuntimeConfiguration(
        version=base.version,
        allowed_namespaces=base.allowed_namespaces + ("test-hotel-reservation",),
        allowed_deployments=base.allowed_deployments + ("geo",),
        min_replicas=base.min_replicas,
        max_replicas=base.max_replicas,
        timeouts=base.timeouts,
        metric_queries={
            **dict(base.metric_queries),
            "availability": MetricQueryDefinition("availability", "up"),
        },
        scenarios={
            **dict(base.scenarios),
            "aiopslab-hotel-reservation": {
                "id": "aiopslab-hotel-reservation",
                "namespace": "test-hotel-reservation",
                "deployment": "geo",
                "metric": "availability",
                "threshold": 1.0,
                "manifest": "aiopslab:hotel-reservation-detection-v1",
                "incident_source": "aiopslab",
                "benchmark_id": "hotel-reservation-detection-v1",
            },
        },
    )
    chaos = FakeChaosAdapter()
    coordinator = FakeCoordinator(approved_report("exp-runtime-1"))
    runtime = ExperimentRuntime(
        configuration=configuration,
        chaos=chaos,
        coordinator_factory=lambda _request: coordinator,
        event_sink=RecordingEventSink(),
        experiment_id_factory=lambda: "exp-runtime-1",
        admission_validator=TestAdmissionValidator(),
    )
    request = ExperimentRuntimeRequest(
        scenario_id="aiopslab-hotel-reservation",
        namespace="test-hotel-reservation",
        deployment="geo",
        metric="availability",
        threshold=1.0,
        mode="real",
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
        incident_source="aiopslab",
        benchmark_id="hotel-reservation-detection-v1",
        detection_context={"accuracy": "Correct", "anomaly_detected": True},
    )

    result = runtime.run(request)

    assert result.status == "recovered"
    assert chaos.calls == []
    assert result.report["incident_source"] == "aiopslab"
    assert result.report["detection"]["accuracy"] == "Correct"


def test_runtime_rejects_target_outside_allowlist_before_fault_injection():
    chaos = FakeChaosAdapter()
    result = runtime_with(chaos=chaos).run(
        replace(real_request(), deployment="not-allowed")
    )
    assert result.status == "blocked"
    assert chaos.calls == []
    assert result.session.status == "blocked"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("namespace", "observability"),
        ("deployment", "checkoutservice"),
        ("metric", "memory"),
        ("threshold", 81.0),
    ),
    ids=("namespace", "deployment", "metric", "threshold"),
)
def test_runtime_rejects_scenario_request_binding_mismatch_before_chaos(
    field, value
):
    chaos = FakeChaosAdapter()
    request = replace(real_request(), **{field: value})

    result = runtime_with(chaos=chaos).run(request)

    assert result.status == "blocked"
    assert field in result.report["error"]
    assert chaos.calls == []


def test_runtime_preserves_timeout_status_and_always_cleans_up():
    chaos = FakeChaosAdapter()
    result = runtime_with(coordinator=TimeoutCoordinator(), chaos=chaos).run(real_request())
    assert result.status == "interrupted"
    assert result.report["error"] == "coordinator timed out"
    assert chaos.calls[-1] == "cleanup:cpu-stress"


def test_dry_run_validation_does_not_claim_recovery_evaluation():
    report = approved_report("dry-run-report")
    report.update(
        {
            "mode": "dry-run",
            "final_status": "dry_run_validated",
            "recovery_monitoring": {
                "status": "not_measured",
                "recovery_success": None,
            },
        }
    )
    request = replace(real_request(), mode=ExecutionMode.DRY_RUN)

    result = runtime_with(
        coordinator=FakeCoordinator(report, mode=ExecutionMode.DRY_RUN)
    ).run(request)

    assert result.status == "dry_run_validated"
    assert result.session.status == "dry_run_validated"
    assert result.session.stages["result"]["status"] == "completed"
    assert result.report["evaluation"]["status"] == "not_applicable"
    assert result.report["evaluation"]["team_reward"] is None


def test_runtime_marks_cleanup_failure_for_human_review_without_hiding_primary_error():
    chaos = FakeChaosAdapter(cleanup_result={"valid": False, "stderr": "delete failed"})
    result = runtime_with(coordinator=RaisingCoordinator(), chaos=chaos).run(real_request())
    assert result.status == "failed"
    assert result.report["error"] == "coordinator failed"
    assert result.report["cleanup_error"] == "delete failed"
    assert result.report["human_review_required"] is True
    assert result.session.human_review_required is True


def test_runtime_honors_cancellation_before_external_operations():
    cancelled = Event()
    cancelled.set()
    chaos = FakeChaosAdapter()
    result = runtime_with(chaos=chaos, cancellation_event=cancelled).run(real_request())
    assert result.status == "cancelled"
    assert chaos.calls == []
    assert result.session.status == "cancelled"


def test_runtime_bridge_keeps_persisted_research_evidence_on_one_experiment_id():
    store = InMemoryResearchEventStore()

    class Coordinator(FakeCoordinator):
        event_store = None

        def run(self, namespace, deployment, metric, threshold):
            self.event_store.append("evidence", {"metric_values": {"cpu": 95.0}})
            return super().run(namespace, deployment, metric, threshold)

    coordinator = Coordinator(approved_report("coordinator-generated-id"))
    result = runtime_with(coordinator=coordinator, artifact_event_store=store).run(real_request())

    assert store.events["evidence"][0]["run_id"] == result.experiment_id
    assert store.final_report["run_id"] == result.experiment_id
    evidence = result.report["evidence"]
    with pytest.raises(TypeError):
        evidence["metric_values"]["cpu"] = 1.0


def test_real_target_lock_spans_injection_and_coordinator_completion(tmp_path):
    entered = Event()
    release = Event()

    class BlockingCoordinator(FakeCoordinator):
        def run(self, namespace, deployment, metric, threshold):
            entered.set()
            release.wait(timeout=2)
            return super().run(namespace, deployment, metric, threshold)

    first_chaos = FakeChaosAdapter()
    second_chaos = FakeChaosAdapter()
    first = runtime_with(
        coordinator=BlockingCoordinator(approved_report("first")),
        chaos=first_chaos,
        lock_dir=str(tmp_path),
    )
    second = runtime_with(lock_dir=str(tmp_path), chaos=second_chaos)
    first_result = []
    thread = Thread(target=lambda: first_result.append(first.run(real_request())))
    thread.start()
    assert entered.wait(timeout=2)

    second_result = second.run(real_request())
    release.set()
    thread.join(timeout=2)

    assert second_result.status == "blocked"
    assert second_chaos.calls == []
    assert first_result[0].status == "recovered"


def test_runtime_rejects_coordinator_mode_mismatch_before_external_operations():
    chaos = FakeChaosAdapter()
    result = runtime_with(
        coordinator=FakeCoordinator(approved_report("wrong"), mode=ExecutionMode.REAL),
        chaos=chaos,
    ).run(mock_request())
    assert result.status == "blocked"
    assert "mode" in result.report["error"]
    assert chaos.calls == []


def test_runtime_rejects_real_request_with_mock_coordinator_before_injection():
    chaos = FakeChaosAdapter()
    result = runtime_with(
        coordinator=FakeCoordinator(approved_report("wrong"), mode=ExecutionMode.MOCK),
        chaos=chaos,
    ).run(real_request())
    assert result.status == "blocked"
    assert "mode" in result.report["error"]
    assert chaos.calls == []


def test_runtime_checks_cancellation_between_preflight_and_injection():
    cancelled = Event()

    class CancellingChaos(FakeChaosAdapter):
        def preflight(self):
            result = super().preflight()
            cancelled.set()
            return result

    chaos = CancellingChaos()
    result = runtime_with(chaos=chaos, cancellation_event=cancelled).run(real_request())
    assert result.status == "cancelled"
    assert chaos.calls == ["preflight"]


def test_runtime_checks_cancellation_after_injection_and_still_cleans_up():
    cancelled = Event()

    class CancellingChaos(FakeChaosAdapter):
        def inject(self, scenario_id):
            application = super().inject(scenario_id)
            cancelled.set()
            return application

    chaos = CancellingChaos()
    result = runtime_with(chaos=chaos, cancellation_event=cancelled).run(real_request())
    assert result.status == "cancelled"
    assert chaos.calls == ["preflight", "inject:cpu-stress", "cleanup:cpu-stress"]


def test_runtime_deadline_interrupts_coordinator_and_persists_terminal_facts():
    configuration = replace(
        runtime_configuration(),
        timeouts={"experiment": 1},
        experiment_seconds=1,
    )
    class CountingStore(InMemoryResearchEventStore):
        def __init__(self):
            super().__init__()
            self.finalize_count = 0

        def finalize(self, report):
            self.finalize_count += 1
            return super().finalize(report)

    store = CountingStore()
    sessions = InMemoryExperimentSessionStore()
    clock_values = iter(([0.0] * 5) + ([2.0] * 10))

    class DeadlineCoordinator(FakeCoordinator):
        def run(self, namespace, deployment, metric, threshold):
            self.runtime_control.check()
            return super().run(namespace, deployment, metric, threshold)

    runtime = ExperimentRuntime(
        configuration=configuration,
        chaos=FakeChaosAdapter(cleanup_result={"valid": False, "stderr": "delete failed"}),
        coordinator_factory=lambda _request: DeadlineCoordinator(approved_report("x")),
        event_sink=RecordingEventSink(),
        artifact_event_store=store,
        session_store=sessions,
        experiment_id_factory=lambda: "exp-deadline",
        clock=lambda: next(clock_values),
        admission_validator=TestAdmissionValidator(),
    )
    result = runtime.run(real_request())

    assert result.status == "interrupted"
    assert result.report["cleanup"]["valid"] is False
    assert result.report["runtime_events"][-1]["stage"] == "completed"
    assert store.final_report == result.to_dict()["report"]
    assert store.finalize_count == 1
    assert sessions.get("exp-deadline") == result.session


def test_registered_production_configuration_has_positive_experiment_deadline():
    configuration = load_runtime_configuration(
        Path(__file__).parents[1] / "config" / "experiment_runtime.json"
    )
    assert configuration.experiment_seconds > 0


def test_blocking_coordinator_is_cancelled_before_cleanup_and_cannot_recover():
    started = Event()
    active = Event()
    recovery_started = Event()
    release = Event()
    clock_calls = 0

    class GatedCoordinator(FakeCoordinator):
        def run(self, namespace, deployment, metric, threshold):
            started.set()
            active.set()
            try:
                while not release.wait(0.001):
                    self.runtime_control.check()
                recovery_started.set()
                return super().run(namespace, deployment, metric, threshold)
            finally:
                active.clear()

    def deterministic_clock():
        nonlocal clock_calls
        clock_calls += 1
        return 0.0 if clock_calls < 8 else 2.0

    class CountingStore(InMemoryResearchEventStore):
        def __init__(self):
            super().__init__()
            self.finalize_count = 0

        def finalize(self, report):
            self.finalize_count += 1
            return super().finalize(report)

    chaos = FakeChaosAdapter()
    store = CountingStore()
    sessions = InMemoryExperimentSessionStore()
    runtime = ExperimentRuntime(
        configuration=replace(runtime_configuration(), experiment_seconds=1),
        chaos=chaos,
        coordinator_factory=lambda _request: GatedCoordinator(
            approved_report("gated")
        ),
        event_sink=RecordingEventSink(),
        artifact_event_store=store,
        session_store=sessions,
        experiment_id_factory=lambda: "exp-gated-timeout",
        clock=deterministic_clock,
        admission_validator=TestAdmissionValidator(),
    )

    result = runtime.run(real_request())

    assert started.is_set()
    assert result.status == "interrupted"
    assert chaos.calls == ["preflight", "inject:cpu-stress", "cleanup:cpu-stress"]
    assert not recovery_started.is_set()
    assert not active.is_set()
    assert store.finalize_count == 1
    assert sessions.list() == (result.session,)
    assert store.final_report == result.to_dict()["report"]


def test_unsupported_non_cooperative_coordinator_is_rejected_before_injection():
    class UnsupportedCoordinator:
        mode = ExecutionMode.REAL

        def run(self, namespace, deployment, metric, threshold):
            raise AssertionError("unsupported coordinator must not run")

    chaos = FakeChaosAdapter()
    result = runtime_with(
        coordinator=UnsupportedCoordinator(),
        chaos=chaos,
        admission_validator=CoordinatorAdmissionValidator(),
    ).run(real_request())

    assert result.status == "blocked"
    assert "MutualSupervisionCoordinator" in result.report["error"]
    assert chaos.calls == []


def _known_production_coordinator(evidence_provider=None):
    provider = evidence_provider or PrometheusKubernetesEvidenceProvider(
        prometheus=PrometheusAdapter("http://prometheus"),
        metric_queries={"cpu": "up"},
        requested_metric="cpu",
    )
    return MutualSupervisionCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice", "checkoutservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        evidence_provider=provider,
        recovery_monitor=KubernetesSnapshotRecoveryMonitor(
            evidence_provider=provider,
            max_attempts=1,
            interval_seconds=0,
        ),
        mode=ExecutionMode.REAL,
        backend="python",
        protocol=load_research_protocol(
            "config/protocol_profiles/four-agent-role-veto-v1.json"
        ),
        adapter_registry=build_default_agent_adapter_registry(),
    )


def test_known_production_coordinator_is_admitted_without_caller_capability_claims():
    coordinator = _known_production_coordinator()
    admission = CoordinatorAdmissionValidator().validate(
        coordinator, real_request(), runtime_configuration()
    )
    assert admission.executor_timeout_seconds > 0
    assert admission.evidence_timeout_seconds > 0


def test_actual_coordinator_with_unsupported_blocking_evidence_is_rejected_before_injection():
    class BlockingEvidenceProvider(PrometheusKubernetesEvidenceProvider):
        pass

    provider = BlockingEvidenceProvider(
        prometheus=PrometheusAdapter("http://prometheus"),
        metric_queries={"cpu": "up"},
        requested_metric="cpu",
    )
    coordinator = _known_production_coordinator(provider)
    chaos = FakeChaosAdapter()
    runtime = ExperimentRuntime(
        configuration=runtime_configuration(),
        chaos=chaos,
        coordinator_factory=lambda _request: coordinator,
        event_sink=RecordingEventSink(),
        experiment_id_factory=lambda: "exp-blocking-evidence",
    )

    result = runtime.run(real_request())

    assert result.status == "blocked"
    assert "evidence provider" in result.report["error"]
    assert chaos.calls == []


def test_self_claiming_non_cooperative_coordinator_is_rejected_before_injection():
    class SelfClaimingCoordinator:
        mode = ExecutionMode.REAL
        runtime_capabilities = CoordinatorRuntimeCapabilities(
            bounded=True,
            cancellable=True,
            finite_stage_io=True,
            deadline_aware=True,
        )

        def run(self, namespace, deployment, metric, threshold):
            raise AssertionError("self-claiming coordinator must not run")

    chaos = FakeChaosAdapter()
    runtime = ExperimentRuntime(
        configuration=runtime_configuration(),
        chaos=chaos,
        coordinator_factory=lambda _request: SelfClaimingCoordinator(),
        event_sink=RecordingEventSink(),
        experiment_id_factory=lambda: "exp-self-claiming",
    )

    result = runtime.run(real_request())

    assert result.status == "blocked"
    assert "MutualSupervisionCoordinator" in result.report["error"]
    assert chaos.calls == []


@pytest.mark.parametrize("case", ("success", "blocked", "cancelled", "cleanup_failed"))
def test_runtime_persists_one_terminal_session_for_every_terminal_path(case):
    sessions = InMemoryExperimentSessionStore()
    chaos = FakeChaosAdapter(
        cleanup_result={"valid": False, "stderr": "delete failed"}
        if case == "cleanup_failed" else None
    )
    cancellation = Event()
    if case == "cancelled":
        cancellation.set()
    coordinator = RaisingCoordinator() if case == "cleanup_failed" else None
    request = (
        replace(real_request(), deployment="not-allowed")
        if case == "blocked" else real_request()
    )
    result = runtime_with(
        coordinator=coordinator,
        chaos=chaos,
        cancellation_event=cancellation,
        session_store=sessions,
    ).run(request)

    assert sessions.list() == (result.session,)
    assert sessions.get(result.experiment_id).experiment_id == result.experiment_id
    assert result.session.status == (
        "blocked" if case == "blocked" else
        "cancelled" if case == "cancelled" else
        "recovered" if case == "success" else
        "failed"
    )

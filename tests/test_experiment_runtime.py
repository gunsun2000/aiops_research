from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from aiops_k8s_agents.experiment_runtime import ExperimentRuntime
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest, RuntimeStage
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.real_evidence import (
    MetricQueryDefinition,
    RuntimeConfiguration,
    load_runtime_configuration,
)
from aiops_k8s_agents.research_event_store import InMemoryResearchEventStore
from aiops_k8s_agents.experiment_session import InMemoryExperimentSessionStore


class RecordingEventSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


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
    def __init__(self, report, mode=ExecutionMode.REAL):
        self.report = report
        self.mode = mode

    def run(self, namespace, deployment, metric, threshold):
        return dict(self.report)


class RaisingCoordinator:
    mode = ExecutionMode.REAL

    def run(self, namespace, deployment, metric, threshold):
        raise RuntimeError("coordinator failed")


class TimeoutCoordinator:
    mode = ExecutionMode.REAL

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
        allowed_namespaces=("online-boutique",),
        allowed_deployments=("paymentservice", "checkoutservice"),
        min_replicas=1,
        max_replicas=5,
        timeouts={"experiment": 30},
        metric_queries={"cpu": MetricQueryDefinition("cpu", "up")},
        scenarios={"cpu-stress": "paymentservice-cpu-stress.yaml"},
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
        "validating", "executing", "observing_recovery", "cleanup", "completed",
    ]
    assert {event.experiment_id for event in result.events} == {result.experiment_id}
    assert {stage["experiment_id"] for stage in result.session.stages.values()} == {
        result.experiment_id
    }


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


def test_runtime_rejects_target_outside_allowlist_before_fault_injection():
    chaos = FakeChaosAdapter()
    result = runtime_with(chaos=chaos).run(
        replace(real_request(), deployment="not-allowed")
    )
    assert result.status == "blocked"
    assert chaos.calls == []
    assert result.session.status == "blocked"


def test_runtime_preserves_timeout_status_and_always_cleans_up():
    chaos = FakeChaosAdapter()
    result = runtime_with(coordinator=TimeoutCoordinator(), chaos=chaos).run(real_request())
    assert result.status == "interrupted"
    assert result.report["error"] == "coordinator timed out"
    assert chaos.calls[-1] == "cleanup:cpu-stress"


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
    configuration = RuntimeConfiguration(
        version="1.0.0",
        allowed_namespaces=("online-boutique",),
        allowed_deployments=("paymentservice", "checkoutservice"),
        min_replicas=1,
        max_replicas=5,
        timeouts={"experiment": 1},
        experiment_seconds=1,
        metric_queries={"cpu": MetricQueryDefinition("cpu", "up")},
        scenarios={"cpu-stress": "paymentservice-cpu-stress.yaml"},
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
    clock_calls = 0

    class GatedCoordinator(FakeCoordinator):
        def run(self, namespace, deployment, metric, threshold):
            started.set()
            active.set()
            try:
                while True:
                    self.runtime_control.check()
                    if recovery_started.is_set():
                        raise AssertionError("recovery started after deadline")
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

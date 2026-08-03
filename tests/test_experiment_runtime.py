from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from aiops_k8s_agents.experiment_runtime import ExperimentRuntime
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest, RuntimeStage
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.real_evidence import MetricQueryDefinition, RuntimeConfiguration
from aiops_k8s_agents.research_event_store import InMemoryResearchEventStore


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
    def __init__(self, report):
        self.report = report

    def run(self, namespace, deployment, metric, threshold):
        return dict(self.report)


class RaisingCoordinator:
    def run(self, namespace, deployment, metric, threshold):
        raise RuntimeError("coordinator failed")


class TimeoutCoordinator:
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
    return ExperimentRuntime(
        configuration=runtime_configuration(),
        chaos=chaos or FakeChaosAdapter(),
        coordinator_factory=lambda _request: coordinator or FakeCoordinator(
            approved_report("exp-runtime-1")
        ),
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

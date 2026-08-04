from __future__ import annotations

from threading import Event

from aiops_k8s_agents.aiopslab_benchmark import AIOpsLabBenchmarkCatalog
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest
from aiops_k8s_agents.integrated_incident import AIOpsLabIncidentAdapter


class RecordingSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def _request(mode="mock"):
    return ExperimentRuntimeRequest(
        scenario_id="aiopslab-hotel-reservation",
        namespace="test-hotel-reservation",
        deployment="geo",
        metric="availability",
        threshold=1.0,
        mode=mode,
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
        incident_source="aiopslab",
        benchmark_id="hotel-reservation-detection-v1",
    )


def test_mock_aiopslab_incident_is_explicitly_synthetic(tmp_path):
    catalog = AIOpsLabBenchmarkCatalog.from_path("config/aiopslab_benchmarks.json")

    class Executor:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("mock mode must not execute external AIOpsLab")

    sink = RecordingSink()
    adapter = AIOpsLabIncidentAdapter(catalog, Executor(), artifact_root=tmp_path)

    context = adapter.prepare(
        _request(),
        experiment_id="exp-aiopslab",
        repetition=1,
        cancellation=Event(),
        event_sink=sink,
    )

    assert context["source"] == "aiopslab"
    assert context["evidence_boundary"] == "synthetic_mock"
    assert context["anomaly_detected"] is True
    assert context["benchmark_id"] == "hotel-reservation-detection-v1"
    assert sink.events[-1].experiment_id == "exp-aiopslab"
    assert sink.events[-1].message == "AIOpsLab detection normalized"

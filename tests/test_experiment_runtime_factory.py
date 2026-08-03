from __future__ import annotations

from pathlib import Path

from aiops_k8s_agents.experiment_runtime_factory import (
    build_experiment_runtime,
    runtime_scenario_catalog,
)
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest
from aiops_k8s_agents.real_evidence import load_runtime_configuration


class RecordingEventSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def write_runtime_config(tmp_path):
    source = Path("config/experiment_runtime.json")
    destination = tmp_path / "experiment_runtime.json"
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def fake_prometheus_fetcher(_url, _query):
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {}, "value": [1780000000.0, "1"]}],
        },
    }


def test_runtime_factory_builds_real_dependencies_from_registered_config(tmp_path):
    configuration_path = write_runtime_config(tmp_path)
    runtime = build_experiment_runtime(
        configuration_path=configuration_path,
        prometheus_url="http://127.0.0.1:9091",
        event_sink=RecordingEventSink(),
        subprocess_runner=lambda _argv: (0, "StressChaos\nNetworkChaos\nPodChaos", ""),
        prometheus_fetcher=fake_prometheus_fetcher,
    )
    assert runtime.configuration.version == "1.0.0"
    assert runtime.chaos.scenario_ids == (
        "cpu-stress",
        "memory-stress",
        "network-delay",
        "pod-kill",
    )


def test_runtime_scenario_catalog_uses_registered_manifest_and_ui_fallback(tmp_path):
    configuration = load_runtime_configuration(write_runtime_config(tmp_path))

    catalog = runtime_scenario_catalog(configuration)

    assert [item["scenario_id"] for item in catalog] == [
        "pod-kill",
        "cpu-stress",
        "memory-stress",
        "network-delay",
    ]
    assert catalog[1]["manifest"] == "k8s/chaos/paymentservice-cpu-stress.yaml"
    assert catalog[1]["namespace"] == "online-boutique"
    assert catalog[1]["deployment"] == "paymentservice"
    assert catalog[1]["metric"] == "cpu"
    assert catalog[1]["threshold"] == 80.0
    assert catalog[1]["ui_fallback"] is True


def test_injected_prometheus_client_is_not_admitted_as_real_runtime(tmp_path):
    runtime = build_experiment_runtime(
        configuration_path=write_runtime_config(tmp_path),
        prometheus_url="http://127.0.0.1:9091",
        event_sink=RecordingEventSink(),
        subprocess_runner=lambda _argv: (0, "StressChaos", ""),
        prometheus_fetcher=fake_prometheus_fetcher,
    )

    result = runtime.run(
        ExperimentRuntimeRequest(
            scenario_id="cpu-stress",
            namespace="online-boutique",
            deployment="paymentservice",
            metric="cpu",
            threshold=80.0,
            mode="real",
            backend="python",
            protocol_profile="four-agent-role-veto-v1",
        )
    )

    assert result.status == "blocked"
    assert "bounded production client" in result.report["error"]

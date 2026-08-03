from __future__ import annotations

from pathlib import Path
import json

import pytest

from aiops_k8s_agents.evidence import FakeEvidenceProvider
from aiops_k8s_agents.experiment_runtime_factory import (
    build_experiment_runtime,
    runtime_scenario_catalog,
)
from aiops_k8s_agents.experiment_runtime_models import ExperimentRuntimeRequest
from aiops_k8s_agents.real_evidence import load_runtime_configuration
from aiops_k8s_agents.recovery_monitor import FakeRecoveryMonitor


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


def test_runtime_factory_selects_requested_registered_protocol(tmp_path):
    runtime = build_experiment_runtime(
        configuration_path=write_runtime_config(tmp_path),
        prometheus_url="http://127.0.0.1:9091",
        event_sink=RecordingEventSink(),
    )
    request = ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode="mock",
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
    )

    coordinator = runtime.coordinator_factory(request)

    assert coordinator.protocol.profile_id == request.protocol_profile


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


def test_runtime_scenario_catalog_accepts_configuration_only_scenario(tmp_path):
    source = json.loads(Path("config/experiment_runtime.json").read_text(encoding="utf-8"))
    source["scenarios"]["disk-pressure"] = {
        "id": "disk-pressure",
        "namespace": "online-boutique",
        "deployment": "paymentservice",
        "metric": "cpu",
        "threshold": 91.0,
        "manifest": "k8s/chaos/paymentservice-cpu-stress.yaml",
    }
    path = tmp_path / "experiment_runtime.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    catalog = runtime_scenario_catalog(load_runtime_configuration(path))

    scenario = next(item for item in catalog if item["scenario_id"] == "disk-pressure")
    assert scenario["namespace"] == "online-boutique"
    assert scenario["deployment"] == "paymentservice"
    assert scenario["metric"] == "cpu"
    assert scenario["threshold"] == 91.0
    assert scenario["manifest"] == "k8s/chaos/paymentservice-cpu-stress.yaml"
    assert scenario["ui_fallback"] is False


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


def test_runtime_factory_rejects_unregistered_protocol_before_coordinator_creation(tmp_path):
    runtime = build_experiment_runtime(
        configuration_path=write_runtime_config(tmp_path),
        prometheus_url="http://127.0.0.1:9091",
        event_sink=RecordingEventSink(),
    )

    request = ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode="mock",
        backend="python",
        protocol_profile="unregistered-profile",
    )

    with pytest.raises(ValueError, match="protocol profile is not registered"):
        runtime.coordinator_factory(request)


def test_factory_mock_run_never_calls_live_evidence_collectors(tmp_path):
    calls = []

    def unexpected_prometheus_fetcher(_url, _query):
        calls.append("prometheus")
        raise AssertionError("mock mode must not query Prometheus")

    def unexpected_kubernetes_collector(**_kwargs):
        calls.append("kubernetes")
        raise AssertionError("mock mode must not collect Kubernetes evidence")

    runtime = build_experiment_runtime(
        configuration_path=write_runtime_config(tmp_path),
        prometheus_url="http://127.0.0.1:9091",
        event_sink=RecordingEventSink(),
        prometheus_fetcher=unexpected_prometheus_fetcher,
        kubernetes_collector=unexpected_kubernetes_collector,
    )
    request = ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode="mock",
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
    )

    result = runtime.run(request)

    assert result.status == "recovered"
    assert result.session.mode == "mock"
    assert calls == []


def test_factory_dry_run_uses_deterministic_non_live_evidence_boundary(tmp_path):
    runtime = build_experiment_runtime(
        configuration_path=write_runtime_config(tmp_path),
        prometheus_url="http://127.0.0.1:9091",
        event_sink=RecordingEventSink(),
    )
    request = ExperimentRuntimeRequest(
        scenario_id="cpu-stress",
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
        mode="dry-run",
        backend="python",
        protocol_profile="four-agent-role-veto-v1",
    )

    coordinator = runtime.coordinator_factory(request)

    assert type(coordinator.evidence_provider) is FakeEvidenceProvider
    assert type(coordinator.recovery_monitor) is FakeRecoveryMonitor

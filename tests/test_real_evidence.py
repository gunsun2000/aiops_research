from __future__ import annotations

import json
import time

import pytest

from aiops_k8s_agents.prometheus import PrometheusSample
from aiops_k8s_agents.real_evidence import (
    EvidenceCollectionError,
    MetricQueryDefinition,
    PrometheusKubernetesEvidenceProvider,
    RuntimeConfiguration,
    load_runtime_configuration,
)


class FakePrometheus:
    def __init__(self, values, samples=None):
        self.values = values
        self.samples = samples

    def query_vector(self, query):
        if self.samples is not None:
            return tuple(self.samples)
        metric = next(
            (name for name, registered in {"cpu": "registered-cpu-query"}.items()
             if registered == query),
            "",
        )
        value = self.values[metric]
        return (
            PrometheusSample(
                labels={"namespace": "online-boutique"},
                timestamp=time.time(),
                value=value,
            ),
        )


def _snapshot(**overrides):
    snapshot = {
        "deployment_status": {"ok": True, "desired_replicas": 2, "available_replicas": 1},
        "pods": {"ok": True, "items": [{"name": "p-1", "uid": "u-1", "phase": "Running", "restarts": 2}]},
    }
    snapshot.update(overrides)
    return snapshot


def test_real_evidence_combines_registered_metric_and_kubernetes_snapshot():
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=FakePrometheus({"cpu": 3.5}),
        metric_queries={"cpu": "registered-cpu-query"},
        requested_metric="cpu",
        kubernetes_collector=lambda **_kwargs: _snapshot(),
    )

    evidence = provider.collect("online-boutique", "paymentservice")

    assert evidence.metric_values == {"cpu": 3.5}
    assert evidence.desired_replicas == 2
    assert evidence.available_replicas == 1
    assert evidence.restart_count == 2
    assert evidence.source == "prometheus+kubernetes"
    event = json.loads(evidence.events[0])
    assert event["query"] == "registered-cpu-query"
    assert event["timestamp"]
    assert event["labels"] == {"namespace": "online-boutique"}


def test_real_evidence_rejects_unregistered_metric():
    with pytest.raises(ValueError, match="unregistered metric"):
        PrometheusKubernetesEvidenceProvider(
            prometheus=FakePrometheus({}),
            metric_queries={},
            requested_metric="arbitrary-promql",
        )


def test_metric_query_render_rejects_unsafe_kubernetes_names():
    definition = MetricQueryDefinition("cpu", "up{namespace=\"{namespace}\"}")

    with pytest.raises(ValueError, match="Kubernetes name"):
        definition.render("Online-Boutique", "paymentservice")


def test_real_evidence_rejects_stale_sample():
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=FakePrometheus({}, [PrometheusSample({}, time.time() - 301, 1.0)]),
        metric_queries={"cpu": "registered-cpu-query"},
        requested_metric="cpu",
        max_sample_age_seconds=300,
        kubernetes_collector=lambda **_kwargs: _snapshot(),
    )

    with pytest.raises(EvidenceCollectionError, match="stale"):
        provider.collect("online-boutique", "paymentservice")


def test_real_evidence_wraps_collection_failures():
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=FakePrometheus({}, samples=[PrometheusSample({}, time.time(), 1.0)]),
        metric_queries={"cpu": "registered-cpu-query"},
        requested_metric="cpu",
        kubernetes_collector=lambda **_kwargs: {"deployment_status": {"ok": False, "stderr": "forbidden"}, "pods": {"ok": True}},
    )

    with pytest.raises(EvidenceCollectionError, match="Kubernetes"):
        provider.collect("online-boutique", "paymentservice")


def test_runtime_configuration_loads_registered_defaults():
    configuration = load_runtime_configuration("config/experiment_runtime.json")

    assert isinstance(configuration, RuntimeConfiguration)
    assert configuration.version == "1.0.0"
    assert configuration.allowed_namespaces == ("online-boutique",)
    assert configuration.metric_queries["cpu"].render("online-boutique", "paymentservice")
    assert configuration.scenarios["pod-kill"] == "k8s/paymentservice-pod-kill.yaml"

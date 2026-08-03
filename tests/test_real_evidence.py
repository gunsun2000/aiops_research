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


class RecordingPrometheus:
    def __init__(self):
        self.queries = []

    def query_vector(self, query):
        self.queries.append(query)
        return (PrometheusSample({}, time.time(), 12.0),)


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


def test_latency_evidence_is_bound_to_requested_deployment():
    configuration = load_runtime_configuration("config/experiment_runtime.json")
    prometheus = RecordingPrometheus()
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=prometheus,
        metric_queries=configuration.metric_queries,
        requested_metric="latency",
        kubernetes_collector=lambda **_kwargs: _snapshot(),
    )

    provider.collect("online-boutique", "checkoutservice")

    query = prometheus.queries[0]
    assert 'target="checkoutservice"' in query
    assert 'target="paymentservice"' not in query


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


@pytest.mark.parametrize("age", [float("inf"), float("nan"), 0.0, -1.0])
def test_runtime_configuration_rejects_non_positive_or_non_finite_sample_age(age):
    with pytest.raises(ValueError, match="max_sample_age_seconds"):
        RuntimeConfiguration(
            version="1.0.0",
            allowed_namespaces=("online-boutique",),
            allowed_deployments=("paymentservice",),
            min_replicas=1,
            max_replicas=5,
            timeouts={},
            metric_queries={"cpu": "up"},
            scenarios={},
            max_sample_age_seconds=age,
        )


@pytest.mark.parametrize("age", [float("inf"), float("nan"), 0.0, -1.0])
def test_runtime_loader_rejects_non_positive_or_non_finite_sample_age(tmp_path, age):
    source = json.loads(open("config/experiment_runtime.json", encoding="utf-8").read())
    source["max_sample_age_seconds"] = age
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match="max_sample_age_seconds"):
        load_runtime_configuration(path)


@pytest.mark.parametrize("age", [float("inf"), float("nan"), 0.0, -1.0])
def test_evidence_provider_rejects_non_positive_or_non_finite_sample_age(age):
    with pytest.raises(ValueError, match="max_sample_age_seconds"):
        PrometheusKubernetesEvidenceProvider(
            prometheus=FakePrometheus({"cpu": 1.0}),
            metric_queries={"cpu": "registered-cpu-query"},
            requested_metric="cpu",
            max_sample_age_seconds=age,
        )


def test_real_evidence_metric_values_are_immutable():
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=FakePrometheus({"cpu": 1.0}),
        metric_queries={"cpu": "registered-cpu-query"},
        requested_metric="cpu",
        kubernetes_collector=lambda **_kwargs: _snapshot(),
    )

    evidence = provider.collect("online-boutique", "paymentservice")

    with pytest.raises(TypeError):
        evidence.metric_values["cpu"] = 99.0
    assert evidence.metric_values["cpu"] == 1.0


@pytest.mark.parametrize(
    "snapshot",
    [
        {"deployment_status": {"ok": True, "desired_replicas": "invalid", "available_replicas": 1}, "pods": {"ok": True, "items": []}},
        {"deployment_status": {"ok": True, "desired_replicas": 1, "available_replicas": 1}, "pods": {"ok": True, "items": [{"restarts": "invalid"}]}},
        {"deployment_status": {"ok": True, "desired_replicas": 1, "available_replicas": 1}, "pods": {"ok": True, "items": ["invalid"]}},
    ],
)
def test_real_evidence_wraps_malformed_kubernetes_payload(snapshot):
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=FakePrometheus({}, [PrometheusSample({}, time.time(), 1.0)]),
        metric_queries={"cpu": "registered-cpu-query"},
        requested_metric="cpu",
        kubernetes_collector=lambda **_kwargs: snapshot,
    )

    with pytest.raises(EvidenceCollectionError, match="Kubernetes"):
        provider.collect("online-boutique", "paymentservice")


@pytest.mark.parametrize("count", [-1, 1.5, True])
@pytest.mark.parametrize("deployment_field", ["desired_replicas", "available_replicas"])
def test_real_evidence_rejects_invalid_deployment_counts(count, deployment_field):
    deployment_status = {
        "ok": True,
        "desired_replicas": 1,
        "available_replicas": 1,
    }
    deployment_status[deployment_field] = count
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=FakePrometheus({}, [PrometheusSample({}, time.time(), 1.0)]),
        metric_queries={"cpu": "registered-cpu-query"},
        requested_metric="cpu",
        kubernetes_collector=lambda **_kwargs: {
            "deployment_status": deployment_status,
            "pods": {"ok": True, "items": []},
        },
    )

    with pytest.raises(EvidenceCollectionError, match="Kubernetes"):
        provider.collect("online-boutique", "paymentservice")


@pytest.mark.parametrize("count", [-1, 1.5, True])
def test_real_evidence_rejects_invalid_restart_counts(count):
    provider = PrometheusKubernetesEvidenceProvider(
        prometheus=FakePrometheus({}, [PrometheusSample({}, time.time(), 1.0)]),
        metric_queries={"cpu": "registered-cpu-query"},
        requested_metric="cpu",
        kubernetes_collector=lambda **_kwargs: {
            "deployment_status": {"ok": True, "desired_replicas": 1, "available_replicas": 1},
            "pods": {"ok": True, "items": [{"restarts": count}]},
        },
    )

    with pytest.raises(EvidenceCollectionError, match="Kubernetes"):
        provider.collect("online-boutique", "paymentservice")


def test_runtime_configuration_loads_registered_defaults():
    configuration = load_runtime_configuration("config/experiment_runtime.json")

    assert isinstance(configuration, RuntimeConfiguration)
    assert configuration.version == "1.0.0"
    assert configuration.allowed_namespaces == ("online-boutique",)
    assert configuration.metric_queries["cpu"].render("online-boutique", "paymentservice")
    assert configuration.scenarios["pod-kill"].manifest == "k8s/paymentservice-pod-kill.yaml"

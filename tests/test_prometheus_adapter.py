import json

import pytest

from aiops_k8s_agents.prometheus import (
    PrometheusAdapter,
    PrometheusAdapterError,
    PrometheusMetricConfig,
    prometheus_result_to_alert_event,
)


def test_prometheus_result_to_alert_event_maps_vector_value():
    response = {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {
                        "namespace": "online-boutique",
                        "service": "paymentservice",
                    },
                    "value": [1780286000.0, "95"],
                }
            ],
        },
    }
    config = PrometheusMetricConfig(
        query='avg(rate(container_cpu_usage_seconds_total{service="paymentservice"}[1m]))',
        metric="cpu",
        threshold=80.0,
        default_namespace="online-boutique",
        default_service="paymentservice",
    )

    alert = prometheus_result_to_alert_event(response, config)

    assert alert.namespace == "online-boutique"
    assert alert.service == "paymentservice"
    assert alert.metric == "cpu"
    assert alert.value == 95.0
    assert alert.threshold == 80.0
    assert "Prometheus metric cpu=95.0" in alert.message


def test_prometheus_adapter_uses_injected_fetcher_without_real_prometheus():
    def fake_fetcher(url, query):
        assert url == "http://prometheus.local"
        assert query == "cpu_query"
        return {
            "status": "success",
            "data": {
                "result": [
                    {
                        "metric": {
                            "namespace": "online-boutique",
                            "deployment": "paymentservice",
                        },
                        "value": [1780286000.0, "91.5"],
                    }
                ]
            },
        }

    adapter = PrometheusAdapter(
        base_url="http://prometheus.local",
        fetcher=fake_fetcher,
    )

    alert = adapter.query_alert(
        PrometheusMetricConfig(
            query="cpu_query",
            metric="cpu",
            threshold=80.0,
            default_namespace="online-boutique",
            default_service="paymentservice",
        )
    )

    assert alert.value == 91.5
    assert alert.service == "paymentservice"


def test_query_vector_preserves_labels_timestamp_and_value():
    adapter = PrometheusAdapter(
        "http://prometheus",
        fetcher=lambda _url, _query: {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{
                    "metric": {"namespace": "online-boutique", "pod": "payment-1"},
                    "value": [1780000000.5, "3.25"],
                }],
            },
        },
    )

    samples = adapter.query_vector("up")

    assert samples[0].labels["pod"] == "payment-1"
    assert samples[0].timestamp == 1780000000.5
    assert samples[0].value == 3.25


def test_query_vector_rejects_non_vector_result():
    adapter = PrometheusAdapter(
        "http://prometheus",
        fetcher=lambda _url, _query: {
            "status": "success",
            "data": {"resultType": "matrix", "result": []},
        },
    )

    with pytest.raises(PrometheusAdapterError, match="vector"):
        adapter.query_vector("up")


def test_ready_returns_true_for_non_empty_vector():
    adapter = PrometheusAdapter(
        "http://prometheus",
        fetcher=lambda _url, _query: {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {}, "value": [1780000000.5, "1"]}],
            },
        },
    )

    assert adapter.ready() is True


def test_ready_returns_false_when_query_fails():
    def failing_fetcher(_url, _query):
        raise OSError("Prometheus is unavailable")

    adapter = PrometheusAdapter("http://prometheus", fetcher=failing_fetcher)

    assert adapter.ready() is False


def test_prometheus_cli_reads_mock_response_file(tmp_path, capsys):
    from aiops_k8s_agents.cli import main

    response_file = tmp_path / "prometheus.json"
    response_file.write_text(
        json.dumps(
            {
                "status": "success",
                "data": {
                    "result": [
                        {
                            "metric": {
                                "namespace": "online-boutique",
                                "service": "paymentservice",
                            },
                            "value": [1780286000.0, "95"],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "prometheus-run",
            "--mode",
            "mock",
            "--mock-response-file",
            str(response_file),
            "--query",
            "cpu_query",
            "--metric",
            "cpu",
            "--threshold",
            "80",
            "--default-namespace",
            "online-boutique",
            "--default-service",
            "paymentservice",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["command"] == (
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
    )
    assert output["metadata"]["input_source"] == "prometheus"


def test_prometheus_cli_returns_json_error_when_adapter_fails(monkeypatch, capsys):
    from aiops_k8s_agents import cli
    from aiops_k8s_agents.cli import main

    class FailingAdapter:
        def __init__(self, _url):
            pass

        def query_alert(self, _config):
            raise RuntimeError("Prometheus HTTP query failed")

    monkeypatch.setattr(cli, "PrometheusAdapter", FailingAdapter)

    exit_code = main(
        [
            "prometheus-run",
            "--mode",
            "mock",
            "--prometheus-url",
            "http://127.0.0.1:9090",
            "--query",
            "up",
            "--metric",
            "cpu",
            "--threshold",
            "0.5",
            "--default-namespace",
            "online-boutique",
            "--default-service",
            "paymentservice",
            "--allowed-namespace",
            "online-boutique",
            "--allowed-deployment",
            "paymentservice",
        ]
    )

    output = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert output["valid"] is False
    assert output["stderr"] == "Prometheus HTTP query failed"
    assert output["metadata"]["input_source"] == "prometheus"

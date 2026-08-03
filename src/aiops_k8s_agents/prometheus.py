from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Callable

from aiops_k8s_agents.models import AlertEvent

PrometheusFetcher = Callable[[str, str], dict[str, Any]]


class PrometheusAdapterError(ValueError):
    """Prometheus 데이터를 AlertEvent로 변환할 수 없을 때 발생합니다."""


@dataclass(frozen=True)
class PrometheusMetricConfig:
    query: str
    metric: str
    threshold: float
    default_namespace: str
    default_service: str


@dataclass(frozen=True)
class PrometheusSample:
    labels: Mapping[str, str]
    timestamp: float
    value: float


@dataclass
class PrometheusAdapter:
    base_url: str
    fetcher: PrometheusFetcher | None = None

    def query_alert(self, config: PrometheusMetricConfig) -> AlertEvent:
        fetcher = self.fetcher or fetch_prometheus_query
        response = fetcher(self.base_url, config.query)
        return prometheus_result_to_alert_event(response, config)

    def query_vector(self, query: str) -> tuple[PrometheusSample, ...]:
        fetcher = self.fetcher or fetch_prometheus_query
        response = fetcher(self.base_url, query)
        return prometheus_result_to_samples(response)

    def ready(self) -> bool:
        try:
            return bool(self.query_vector("vector(1)"))
        except (OSError, ValueError):
            return False


def fetch_prometheus_query(base_url: str, query: str) -> dict[str, Any]:
    url = _query_url(base_url, query)
    with urllib.request.urlopen(url, timeout=10) as response:
        payload = response.read().decode("utf-8")
    return dict(json.loads(payload))


def prometheus_result_to_alert_event(
    response: dict[str, Any],
    config: PrometheusMetricConfig,
) -> AlertEvent:
    if response.get("status") != "success":
        raise PrometheusAdapterError("Prometheus query did not return success")

    result = response.get("data", {}).get("result", [])
    if not result:
        raise PrometheusAdapterError("Prometheus query returned no vector results")

    first = result[0]
    labels = dict(first.get("metric") or {})
    value = _extract_value(first)
    namespace = labels.get("namespace") or config.default_namespace
    service = (
        labels.get("service")
        or labels.get("deployment")
        or labels.get("pod")
        or config.default_service
    )

    return AlertEvent(
        namespace=namespace,
        service=service,
        metric=config.metric,
        value=value,
        threshold=config.threshold,
        message=(
            f"Prometheus metric {config.metric}={value:.1f} "
            f"threshold={config.threshold:.1f} service={service}"
        ),
    )


def prometheus_result_to_samples(
    response: Mapping[str, Any],
) -> tuple[PrometheusSample, ...]:
    if response.get("status") != "success":
        raise PrometheusAdapterError("Prometheus query did not return success")

    data = response.get("data")
    if not isinstance(data, Mapping) or data.get("resultType") != "vector":
        raise PrometheusAdapterError("Prometheus query did not return a vector result")

    result = data.get("result")
    if not isinstance(result, list):
        raise PrometheusAdapterError("Prometheus vector result must contain a result list")

    return tuple(_extract_sample(item) for item in result)


def load_prometheus_response(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def _extract_value(result: dict[str, Any]) -> float:
    value = result.get("value")
    if not isinstance(value, list) or len(value) < 2:
        raise PrometheusAdapterError("Prometheus vector result must contain value")
    try:
        return float(value[1])
    except (TypeError, ValueError) as exc:
        raise PrometheusAdapterError(f"Prometheus value is not numeric: {value[1]}") from exc


def _extract_sample(result: Any) -> PrometheusSample:
    if not isinstance(result, Mapping):
        raise PrometheusAdapterError("Prometheus vector sample must be an object")

    labels = result.get("metric")
    if not isinstance(labels, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in labels.items()
    ):
        raise PrometheusAdapterError("Prometheus vector sample must contain string labels")

    value = result.get("value")
    if not isinstance(value, list) or len(value) != 2:
        raise PrometheusAdapterError("Prometheus vector result must contain timestamp and value")

    try:
        timestamp = float(value[0])
        sample_value = float(value[1])
    except (TypeError, ValueError) as exc:
        raise PrometheusAdapterError("Prometheus vector sample values must be numeric") from exc
    if not math.isfinite(timestamp) or not math.isfinite(sample_value):
        raise PrometheusAdapterError("Prometheus vector sample values must be finite")

    return PrometheusSample(MappingProxyType(dict(labels)), timestamp, sample_value)


def _query_url(base_url: str, query: str) -> str:
    base = base_url.rstrip("/")
    encoded = urllib.parse.urlencode({"query": query})
    return f"{base}/api/v1/query?{encoded}"

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
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


@dataclass
class PrometheusAdapter:
    base_url: str
    fetcher: PrometheusFetcher | None = None

    def query_alert(self, config: PrometheusMetricConfig) -> AlertEvent:
        fetcher = self.fetcher or fetch_prometheus_query
        response = fetcher(self.base_url, config.query)
        return prometheus_result_to_alert_event(response, config)


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


def _query_url(base_url: str, query: str) -> str:
    base = base_url.rstrip("/")
    encoded = urllib.parse.urlencode({"query": query})
    return f"{base}/api/v1/query?{encoded}"

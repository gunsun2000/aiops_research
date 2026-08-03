from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from aiops_k8s_agents.evidence import EvidenceSnapshot
from aiops_k8s_agents.kubernetes_status import collect_kubernetes_snapshot
from aiops_k8s_agents.prometheus import PrometheusSample

KubernetesSnapshotCollector = Callable[..., dict[str, Any]]
_KUBERNETES_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class _ImmutableMetricValues(dict[str, float]):
    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("metric_values is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __ior__(self, other: Any) -> _ImmutableMetricValues:
        self._immutable(other)
        return self


class EvidenceCollectionError(RuntimeError):
    """Raised when real evidence cannot be collected safely."""


@dataclass(frozen=True)
class MetricQueryDefinition:
    metric: str
    query: str

    def __post_init__(self) -> None:
        if not isinstance(self.metric, str) or not self.metric.strip():
            raise ValueError("metric must not be empty")
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("query must not be empty")
        object.__setattr__(self, "metric", self.metric.strip().lower().replace("-", "_"))
        object.__setattr__(self, "query", self.query.strip())

    def render(self, namespace: str, deployment: str) -> str:
        namespace = _validate_kubernetes_name("namespace", namespace)
        deployment = _validate_kubernetes_name("deployment", deployment)
        return self.query.replace("{namespace}", namespace).replace("{deployment}", deployment)


@dataclass(frozen=True)
class RuntimeConfiguration:
    version: str
    allowed_namespaces: tuple[str, ...]
    allowed_deployments: tuple[str, ...]
    min_replicas: int
    max_replicas: int
    timeouts: Mapping[str, int]
    metric_queries: Mapping[str, MetricQueryDefinition]
    scenarios: Mapping[str, str]
    max_sample_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version must not be empty")
        if self.min_replicas < 1 or self.max_replicas < self.min_replicas:
            raise ValueError("replica bounds are invalid")
        _validate_sample_age(self.max_sample_age_seconds)
        definitions = {
            name.strip().lower().replace("-", "_"): (
                value if isinstance(value, MetricQueryDefinition)
                else MetricQueryDefinition(name, str(value))
            )
            for name, value in self.metric_queries.items()
        }
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "allowed_namespaces", tuple(self.allowed_namespaces))
        object.__setattr__(self, "allowed_deployments", tuple(self.allowed_deployments))
        object.__setattr__(self, "timeouts", MappingProxyType(dict(self.timeouts)))
        object.__setattr__(self, "metric_queries", MappingProxyType(definitions))
        object.__setattr__(self, "scenarios", MappingProxyType(dict(self.scenarios)))
        object.__setattr__(self, "max_sample_age_seconds", float(self.max_sample_age_seconds))


def load_runtime_configuration(path: str | Path) -> RuntimeConfiguration:
    with Path(path).open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("runtime configuration must be a JSON object")
    required = {
        "version", "allowed_namespaces", "allowed_deployments", "min_replicas",
        "max_replicas", "timeouts", "metric_queries", "scenarios",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"runtime configuration missing: {', '.join(missing)}")
    return RuntimeConfiguration(
        version=payload["version"],
        allowed_namespaces=tuple(payload["allowed_namespaces"]),
        allowed_deployments=tuple(payload["allowed_deployments"]),
        min_replicas=int(payload["min_replicas"]),
        max_replicas=int(payload["max_replicas"]),
        timeouts=dict(payload["timeouts"]),
        metric_queries=dict(payload["metric_queries"]),
        scenarios=dict(payload["scenarios"]),
        max_sample_age_seconds=float(payload.get("max_sample_age_seconds", 300.0)),
    )


@dataclass(frozen=True)
class PrometheusKubernetesEvidenceProvider:
    prometheus: Any
    metric_queries: Mapping[str, str | MetricQueryDefinition]
    requested_metric: str
    kubernetes_collector: KubernetesSnapshotCollector = collect_kubernetes_snapshot
    max_sample_age_seconds: float = 300.0

    def __post_init__(self) -> None:
        metric = self.requested_metric.strip().lower().replace("-", "_")
        _validate_sample_age(self.max_sample_age_seconds)
        definitions = {
            name.strip().lower().replace("-", "_"): (
                value if isinstance(value, MetricQueryDefinition)
                else MetricQueryDefinition(name, value)
            )
            for name, value in self.metric_queries.items()
        }
        if metric not in definitions:
            raise ValueError(f"unregistered metric: {self.requested_metric}")
        object.__setattr__(self, "requested_metric", metric)
        object.__setattr__(self, "metric_queries", MappingProxyType(definitions))
        object.__setattr__(self, "max_sample_age_seconds", float(self.max_sample_age_seconds))

    def collect(self, namespace: str, deployment: str) -> EvidenceSnapshot:
        query = self.metric_queries[self.requested_metric].render(namespace, deployment)
        try:
            samples = tuple(self.prometheus.query_vector(query))
            sample = self._usable_sample(samples)
        except EvidenceCollectionError:
            raise
        except Exception as exc:
            raise EvidenceCollectionError(f"Prometheus collection failed: {exc}") from exc

        try:
            snapshot = self.kubernetes_collector(namespace=namespace, deployment=deployment)
            if not isinstance(snapshot, Mapping):
                raise ValueError("snapshot must be a mapping")
            deployment_status = snapshot.get("deployment_status") or {}
            pod_status = snapshot.get("pods") or {}
            if not isinstance(deployment_status, Mapping) or not isinstance(pod_status, Mapping):
                raise ValueError("snapshot status fields must be mappings")
            if deployment_status.get("ok") is not True or pod_status.get("ok") is not True:
                details = deployment_status.get("stderr") or pod_status.get("stderr") or "unavailable"
                raise EvidenceCollectionError(f"Kubernetes collection failed: {details}")
            pods = pod_status.get("items") or []
            if not isinstance(pods, list) or any(not isinstance(pod, Mapping) for pod in pods):
                raise ValueError("pod items must be mappings")
            desired_replicas = _validate_count(
                deployment_status.get("desired_replicas", 0), "desired_replicas"
            )
            available_replicas = _validate_count(
                deployment_status.get("available_replicas", 0), "available_replicas"
            )
            restart_count = sum(
                _validate_count(pod.get("restarts", 0), "restarts") for pod in pods
            )
            pod_statuses = tuple(str(pod.get("phase", "Unknown")) for pod in pods) or ("Unknown",)
            pod_identities = tuple(str(pod.get("uid") or pod.get("name") or "") for pod in pods)
        except EvidenceCollectionError:
            raise
        except Exception as exc:
            raise EvidenceCollectionError(f"Kubernetes collection failed: {exc}") from exc

        event = json.dumps(
            {
                "metric": self.requested_metric,
                "query": _sanitize_text(query),
                "timestamp": sample.timestamp,
                "labels": _sanitize_labels(sample.labels),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return EvidenceSnapshot(
            namespace=namespace,
            deployment=deployment,
            metric_values=_ImmutableMetricValues({self.requested_metric: sample.value}),
            desired_replicas=desired_replicas,
            available_replicas=available_replicas,
            restart_count=restart_count,
            pod_statuses=pod_statuses,
            pod_identities=pod_identities,
            events=(event,),
            source="prometheus+kubernetes",
        )

    def _usable_sample(self, samples: tuple[PrometheusSample, ...]) -> PrometheusSample:
        now = time.time()
        usable = [
            sample for sample in samples
            if sample.timestamp <= now and now - sample.timestamp <= self.max_sample_age_seconds
        ]
        if len(usable) != 1:
            if len(usable) == 0 and samples:
                raise EvidenceCollectionError("Prometheus sample is stale or from the future")
            raise EvidenceCollectionError("Prometheus query must return exactly one usable sample")
        return usable[0]


def _validate_kubernetes_name(kind: str, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{kind} must be a Kubernetes name")
    value = value.strip()
    if not _KUBERNETES_NAME.fullmatch(value) or len(value) > 63:
        raise ValueError(f"{kind} is not a valid Kubernetes name")
    return value


def _validate_sample_age(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("max_sample_age_seconds must be finite and positive")
    if not isfinite(value) or value <= 0:
        raise ValueError("max_sample_age_seconds must be finite and positive")


def _validate_count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _sanitize_text(value: str) -> str:
    return "".join(char for char in value if char.isprintable())[:2048]


def _sanitize_labels(labels: Mapping[str, str]) -> dict[str, str]:
    return {
        _sanitize_text(str(key))[:128]: _sanitize_text(str(value))[:256]
        for key, value in labels.items()
    }

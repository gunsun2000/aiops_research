from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

from aiops_k8s_agents.kubernetes_status import collect_kubernetes_snapshot


@dataclass(frozen=True)
class EvidenceSnapshot:
    namespace: str
    deployment: str
    metric_values: dict[str, float] = field(default_factory=dict)
    desired_replicas: int = 1
    available_replicas: int = 1
    restart_count: int = 0
    pod_statuses: tuple[str, ...] = ("Running",)
    pod_identities: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    latency_ms: float | None = None
    error_rate: float | None = None
    log_summary: str = ""
    source: str = "fake"

    def primary_metric_value(self, metric: str) -> float | None:
        normalized = metric.strip().lower().replace("-", "_")
        return self.metric_values.get(normalized)

    def to_summary(self) -> dict:
        return asdict(self)


class EvidenceProvider(Protocol):
    def collect(self, namespace: str, deployment: str) -> EvidenceSnapshot:
        """Collect one operation evidence snapshot."""


@dataclass(frozen=True)
class FakeEvidenceProvider:
    """In-memory evidence provider for deterministic mock and unit tests."""

    snapshot: EvidenceSnapshot

    def collect(self, namespace: str, deployment: str) -> EvidenceSnapshot:
        return EvidenceSnapshot(
            namespace=namespace,
            deployment=deployment,
            metric_values=dict(self.snapshot.metric_values),
            desired_replicas=self.snapshot.desired_replicas,
            available_replicas=self.snapshot.available_replicas,
            restart_count=self.snapshot.restart_count,
            pod_statuses=tuple(self.snapshot.pod_statuses),
            pod_identities=tuple(self.snapshot.pod_identities),
            events=tuple(self.snapshot.events),
            latency_ms=self.snapshot.latency_ms,
            error_rate=self.snapshot.error_rate,
            log_summary=self.snapshot.log_summary,
            source="fake",
        )

    @classmethod
    def cpu_saturation(
        cls,
        namespace: str,
        deployment: str,
        value: float,
        desired_replicas: int = 1,
        available_replicas: int = 1,
    ) -> FakeEvidenceProvider:
        return cls(
            EvidenceSnapshot(
                namespace=namespace,
                deployment=deployment,
                metric_values={"cpu": value},
                desired_replicas=desired_replicas,
                available_replicas=available_replicas,
                restart_count=0,
                latency_ms=220.0 if value >= 80.0 else 40.0,
                events=("High CPU saturation signal",),
            )
        )


@dataclass(frozen=True)
class KubernetesEvidenceProvider:
    """Optional provider backed by kubectl snapshots.

    This provider intentionally collects conservative Kubernetes status only.
    Prometheus and log enrichment can be layered on later without changing the
    autonomous coordinator contract.
    """

    source: str = "kubernetes"

    def collect(self, namespace: str, deployment: str) -> EvidenceSnapshot:
        snapshot = collect_kubernetes_snapshot(namespace=namespace, deployment=deployment)
        deployment_status = snapshot.get("deployment_status") or {}
        pod_status = snapshot.get("pods") or {}
        pods = pod_status.get("items") or []
        restart_count = sum(int(pod.get("restarts", 0) or 0) for pod in pods)
        pod_statuses = tuple(str(pod.get("phase", "Unknown")) for pod in pods)
        pod_identities = tuple(
            str(pod.get("uid") or pod.get("name") or "")
            for pod in pods
            if pod.get("uid") or pod.get("name")
        )
        return EvidenceSnapshot(
            namespace=namespace,
            deployment=deployment,
            metric_values={},
            desired_replicas=int(deployment_status.get("desired_replicas", 0) or 0),
            available_replicas=int(
                deployment_status.get("available_replicas", 0) or 0
            ),
            restart_count=restart_count,
            pod_statuses=pod_statuses or ("Unknown",),
            pod_identities=pod_identities,
            events=(),
            source=self.source,
        )

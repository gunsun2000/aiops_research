from __future__ import annotations

from dataclasses import dataclass

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.models import AlertEvent, Diagnosis


@dataclass(frozen=True)
class AIServiceHASupportAgent:
    """Detects service availability risk and decides whether HA recovery is needed."""

    name: str = "AIServiceHASupportAgent"

    def diagnose(self, alert: AlertEvent) -> tuple[Diagnosis, AgentDecision]:
        metric = _normalize_metric(alert.metric)
        cause = _diagnosis_cause(metric, alert.value, alert.threshold)
        if cause:
            severity = _severity(metric, alert.value, alert.threshold)
            diagnosis = Diagnosis(
                service=alert.service,
                cause=cause,
                severity=severity,
                confidence=0.95,
            )
            return diagnosis, AgentDecision(
                agent=self.name,
                action="ha_scale_out_required",
                reward=0.90,
                approved=True,
                reason=(
                    f"{alert.service} {metric} value={alert.value:.1f} "
                    f"threshold={alert.threshold:.1f}; HA scale-out is required."
                ),
            )

        diagnosis = Diagnosis(
            service=alert.service,
            cause="no_action_required",
            severity="info",
            confidence=0.8,
        )
        return diagnosis, AgentDecision(
            agent=self.name,
            action="ha_no_action",
            reward=0.20,
            approved=False,
            reason=f"{alert.service} does not need an HA recovery action now.",
        )


def _normalize_metric(metric: str) -> str:
    return metric.strip().lower().replace("-", "_")


def _diagnosis_cause(metric: str, value: float, threshold: float) -> str:
    high_is_bad = {
        "cpu": "cpu_saturation",
        "memory": "memory_saturation",
        "latency": "latency_saturation",
        "request_latency": "latency_saturation",
        "network_error": "network_degradation",
        "network_errors": "network_degradation",
        "restart_count": "pod_restarts",
        "restarts": "pod_restarts",
    }
    low_is_bad = {
        "availability": "low_availability",
        "available_replicas": "low_availability",
        "ready_replicas": "low_availability",
        "pod_availability": "low_availability",
    }

    if metric in high_is_bad and value >= threshold:
        return high_is_bad[metric]
    if metric in low_is_bad and value <= threshold:
        return low_is_bad[metric]
    return ""


def _severity(metric: str, value: float, threshold: float) -> str:
    if metric in {"availability", "available_replicas", "ready_replicas"}:
        return "critical" if value <= 0 else "warning"
    if metric in {"restart_count", "restarts"}:
        return "critical" if value >= threshold * 2 else "warning"
    return "critical" if value >= 90 else "warning"

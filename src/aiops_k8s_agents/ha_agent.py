from __future__ import annotations

from dataclasses import dataclass, field

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.agent_decision_policy import (
    AgentDecisionPolicy,
    default_agent_decision_policy,
)
from aiops_k8s_agents.models import AlertEvent, Diagnosis


@dataclass(frozen=True)
class AIServiceHASupportAgent:
    """Detects service availability risk and decides whether HA recovery is needed."""

    name: str = "AIServiceHASupportAgent"
    policy: AgentDecisionPolicy = field(default_factory=default_agent_decision_policy)

    def diagnose(self, alert: AlertEvent) -> tuple[Diagnosis, AgentDecision]:
        metric_policy = self.policy.metric_policy_for(alert.metric)
        normalized_metric = (
            metric_policy.canonical_name if metric_policy else _normalize_metric(alert.metric)
        )
        threshold_exceeded = (
            metric_policy.threshold_exceeded(alert.value, alert.threshold)
            if metric_policy
            else False
        )
        evidence = {
            "raw_metric": alert.metric,
            "normalized_metric": normalized_metric,
            "value": alert.value,
            "threshold": alert.threshold,
            "threshold_exceeded": threshold_exceeded,
            "signal_direction": (
                metric_policy.signal_direction if metric_policy else "unknown"
            ),
            "comparison": _comparison_text(alert.value, alert.threshold, metric_policy),
            "severity_score": (
                metric_policy.severity_score(alert.value, alert.threshold)
                if metric_policy
                else 0.0
            ),
        }
        if metric_policy and threshold_exceeded:
            severity = metric_policy.severity_label(alert.value, alert.threshold)
            diagnosis = Diagnosis(
                service=alert.service,
                cause=metric_policy.cause,
                severity=severity,
                confidence=0.95,
                evidence=evidence,
            )
            preferred_action = self.policy.preferred_action_for(metric_policy.cause)
            ha_action = (
                "ha_scale_out_required"
                if preferred_action == "scale_out"
                else "ha_recovery_required"
            )
            return diagnosis, AgentDecision(
                agent=self.name,
                action=ha_action,
                reward=self.policy.reward_for("ha_recovery_required", 0.90),
                approved=True,
                reason=(
                    f"{alert.service} {normalized_metric} value={alert.value:.1f} "
                    f"threshold={alert.threshold:.1f}; cause={metric_policy.cause} "
                    f"severity={severity}; preferred_action={preferred_action}."
                ),
                parameters={
                    "metric": normalized_metric,
                    "cause": metric_policy.cause,
                    "severity": severity,
                    "severity_score": f"{evidence['severity_score']:.3f}",
                    "signal_direction": metric_policy.signal_direction,
                    "preferred_action": preferred_action,
                },
            )

        diagnosis = Diagnosis(
            service=alert.service,
            cause="no_action_required",
            severity="info",
            confidence=0.8,
            evidence=evidence,
        )
        return diagnosis, AgentDecision(
            agent=self.name,
            action="ha_no_action",
            reward=self.policy.reward_for("ha_no_action", 0.20),
            approved=False,
            reason=f"{alert.service} does not need an HA recovery action now.",
        )


def _normalize_metric(metric: str) -> str:
    return metric.strip().lower().replace("-", "_")


def _comparison_text(value: float, threshold: float, metric_policy: object | None) -> str:
    signal_direction = getattr(metric_policy, "signal_direction", "")
    if signal_direction == "low_is_bad":
        return f"{value:.3f} <= {threshold:.3f}"
    return f"{value:.3f} >= {threshold:.3f}"

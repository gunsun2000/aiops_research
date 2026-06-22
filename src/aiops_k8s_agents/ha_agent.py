from __future__ import annotations

from dataclasses import dataclass, field

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.agent_decision_policy import (
    AgentDecisionPolicy,
    default_agent_decision_policy,
)
from aiops_k8s_agents.evidence import EvidenceSnapshot
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

    def diagnose_evidence(
        self,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> tuple[Diagnosis, AgentDecision]:
        normalized_metric = _normalize_metric(metric)
        value = evidence.primary_metric_value(normalized_metric)
        missing_evidence: list[str] = []
        if value is None:
            missing_evidence.append(normalized_metric)

        cause = "no_action_required"
        severity = "info"
        confidence = 0.60
        possible_root_causes: list[str] = []
        preferred_action = "observe_only"

        if value is not None and value >= threshold:
            cause = _cause_from_metric(normalized_metric)
            severity = "critical" if value >= threshold * 1.15 else "warning"
            confidence = 0.88
            preferred_action = self.policy.preferred_action_for(cause)
            possible_root_causes.append(cause)

        if evidence.restart_count > 0:
            possible_root_causes.append("pod_instability")
            if normalized_metric == "restart_count" or cause == "no_action_required":
                cause = "pod_restarts"
                severity = "warning" if evidence.restart_count <= 2 else "critical"
                confidence = max(confidence, 0.86)
                preferred_action = self.policy.preferred_action_for(cause)

        if evidence.available_replicas < evidence.desired_replicas:
            possible_root_causes.append("low_availability")
            cause = "low_availability"
            severity = "critical"
            confidence = max(confidence, 0.90)
            preferred_action = self.policy.preferred_action_for(cause)

        approved = cause != "no_action_required"
        action = (
            "ha_recovery_required"
            if approved
            else "ha_no_action"
        )
        diagnosis_evidence = {
            "supporting_evidence": evidence.to_summary(),
            "missing_evidence": missing_evidence,
            "possible_root_causes": sorted(set(possible_root_causes)),
            "normalized_metric_name": normalized_metric,
            "threshold_comparison": (
                "missing"
                if value is None
                else _comparison_text(value, threshold, None)
            ),
            "diagnosis_reason": (
                f"cause={cause}; severity={severity}; preferred_action={preferred_action}"
            ),
            "recommended_next_observation": (
                "collect_missing_metric"
                if missing_evidence
                else "monitor_after_recovery_action"
            ),
            "preferred_action": preferred_action,
        }
        diagnosis = Diagnosis(
            service=evidence.deployment,
            cause=cause,
            severity=severity,
            confidence=confidence,
            evidence=diagnosis_evidence,
        )
        return diagnosis, AgentDecision(
            agent=self.name,
            action=action,
            reward=self.policy.reward_for(action, 0.90 if approved else 0.20),
            approved=approved,
            reason=diagnosis_evidence["diagnosis_reason"],
            parameters={
                "cause": cause,
                "severity": severity,
                "confidence": f"{confidence:.2f}",
                "preferred_action": preferred_action,
            },
        )


def _normalize_metric(metric: str) -> str:
    return metric.strip().lower().replace("-", "_")


def _comparison_text(value: float, threshold: float, metric_policy: object | None) -> str:
    signal_direction = getattr(metric_policy, "signal_direction", "")
    if signal_direction == "low_is_bad":
        return f"{value:.3f} <= {threshold:.3f}"
    return f"{value:.3f} >= {threshold:.3f}"


def _cause_from_metric(metric: str) -> str:
    if metric in {"cpu", "cpu_usage", "cpu_utilization"}:
        return "cpu_saturation"
    if metric in {"memory", "memory_usage", "memory_working_set"}:
        return "memory_saturation"
    if metric in {"latency", "duration", "request_latency"}:
        return "latency_saturation"
    if metric in {"error_rate", "errors"}:
        return "network_degradation"
    if metric in {"restart_count", "restarts"}:
        return "pod_restarts"
    if metric in {"availability", "available_replicas"}:
        return "low_availability"
    return "cpu_saturation"

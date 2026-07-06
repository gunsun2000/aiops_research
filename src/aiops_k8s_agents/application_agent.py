from __future__ import annotations

from dataclasses import dataclass, field
from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.agent_decision_policy import (
    AgentDecisionPolicy,
    default_agent_decision_policy,
)
from aiops_k8s_agents.evidence import EvidenceSnapshot
from aiops_k8s_agents.models import (
    AlertEvent,
    Diagnosis,
    RecoveryAction,
    RecoveryActionCandidate,
    RecoveryActionKind,
)


@dataclass(frozen=True)
class AIApplicationManagementAgent:
    """Builds application-level Kubernetes control actions."""

    name: str = "AIApplicationManagementAgent"
    default_cpu_replicas: int = 3
    policy: AgentDecisionPolicy = field(default_factory=default_agent_decision_policy)

    def propose(
        self,
        alert: AlertEvent,
        diagnosis: Diagnosis,
    ) -> tuple[RecoveryAction, AgentDecision]:
        if diagnosis.cause not in _SUPPORTED_CAUSES:
            raise ValueError(
                f"unsupported diagnosis for application action: {diagnosis.cause}"
            )

        preferred_action = self.policy.preferred_action_for(diagnosis.cause)
        action_kind = _to_recovery_action_kind(preferred_action)
        replicas = (
            self.policy.recommended_replicas(diagnosis.severity)
            if action_kind == RecoveryActionKind.SCALE_OUT
            else None
        )
        if replicas is None and action_kind == RecoveryActionKind.SCALE_OUT:
            replicas = self.default_cpu_replicas

        action = RecoveryAction(
            namespace=alert.namespace,
            deployment=alert.service,
            kind=action_kind,
            replicas=replicas,
            reason=(
                f"{diagnosis.service} {diagnosis.cause} "
                f"severity={diagnosis.severity} confidence={diagnosis.confidence:.2f}"
            ),
        )
        decision_action = _application_decision_action(action_kind)
        parameters = {
            "namespace": action.namespace,
            "deployment": action.deployment,
            "action_kind": action.kind.value,
            "cause": diagnosis.cause,
            "severity": diagnosis.severity,
        }
        if action.replicas is not None:
            parameters["replicas"] = str(action.replicas)

        return action, AgentDecision(
            agent=self.name,
            action=decision_action,
            reward=self.policy.reward_for(decision_action, 0.85),
            approved=True,
            reason=(
                f"Select {action.kind.value} for {alert.service} from policy "
                f"because cause={diagnosis.cause}, severity={diagnosis.severity}."
            ),
            parameters=parameters,
        )

    def generate_recovery_candidates(
        self,
        namespace: str,
        deployment: str,
        diagnosis: Diagnosis,
        evidence: EvidenceSnapshot,
    ) -> list[RecoveryActionCandidate]:
        preferred_action = self.policy.preferred_action_for(diagnosis.cause)
        baseline_replicas = max(evidence.desired_replicas, 1)
        target_replicas = max(
            baseline_replicas + 1,
            self.policy.recommended_replicas(diagnosis.severity),
        )
        target_replicas = min(target_replicas, 5)

        candidates = [
            RecoveryActionCandidate(
                action=RecoveryAction(
                    namespace=namespace,
                    deployment=deployment,
                    kind=RecoveryActionKind.OBSERVE_ONLY,
                    reason="Collect more evidence before changing Kubernetes state.",
                ),
                reason="Evidence is insufficient or risk is low enough to observe first.",
                expected_effect="No resource change; confirms whether Kubernetes self-recovers.",
                risk_level="low",
                estimated_cost=0.0,
                confidence=0.55 if diagnosis.confidence >= 0.8 else 0.75,
                priority=0.95 if preferred_action == "observe_only" else 0.40,
            ),
            RecoveryActionCandidate(
                action=RecoveryAction(
                    namespace=namespace,
                    deployment=deployment,
                    kind=RecoveryActionKind.ROLLOUT_RESTART,
                    reason="Restart pods when restart or unhealthy evidence is present.",
                ),
                reason="Pod instability or memory symptoms can be cleared by restart.",
                expected_effect="Refreshes pods without increasing replica cost.",
                risk_level="medium",
                estimated_cost=0.10,
                confidence=0.80 if diagnosis.cause in {"pod_restarts", "memory_saturation"} else 0.50,
                priority=0.95 if preferred_action == "rollout_restart" else 0.55,
            ),
            RecoveryActionCandidate(
                action=RecoveryAction(
                    namespace=namespace,
                    deployment=deployment,
                    kind=RecoveryActionKind.SCALE_OUT,
                    replicas=target_replicas,
                    reason="Scale out when workload saturation is likely.",
                ),
                reason="CPU, latency, or availability pressure can be mitigated by replicas.",
                expected_effect="Adds serving capacity and improves availability headroom.",
                risk_level="medium",
                estimated_cost=float(max(target_replicas - baseline_replicas, 0)),
                confidence=0.88 if diagnosis.cause in {"cpu_saturation", "latency_saturation", "low_availability"} else 0.45,
                priority=0.95 if preferred_action == "scale_out" else 0.50,
            ),
        ]
        return sorted(
            candidates,
            key=lambda candidate: (candidate.priority, candidate.confidence),
            reverse=True,
        )


_SUPPORTED_CAUSES = {
    "cpu_saturation",
    "memory_saturation",
    "latency_saturation",
    "network_degradation",
    "pod_restarts",
    "low_availability",
}


def _to_recovery_action_kind(action: str) -> RecoveryActionKind:
    try:
        return RecoveryActionKind(action)
    except ValueError as exc:
        raise ValueError(f"unsupported policy action candidate: {action}") from exc


def _application_decision_action(kind: RecoveryActionKind) -> str:
    if kind == RecoveryActionKind.OBSERVE_ONLY:
        return "app_observe_only"
    if kind == RecoveryActionKind.ROLLOUT_RESTART:
        return "app_rollout_restart"
    if kind == RecoveryActionKind.SCALE_OUT:
        return "app_scale_deployment"
    raise ValueError(f"unsupported recovery action kind: {kind.value}")

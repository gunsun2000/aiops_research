from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.agent_decision_policy import (
    AgentDecisionPolicy,
    default_agent_decision_policy,
)
from aiops_k8s_agents.models import AlertEvent, Diagnosis, RecoveryAction, RecoveryActionKind


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

    def plan_deployment(
        self,
        deployment_plan: Any,
        placement_decision: Any | None = None,
    ) -> AgentDecision:
        if not getattr(deployment_plan, "valid", False):
            return AgentDecision(
                agent=self.name,
                action="app_deployment_plan_rejected",
                reward=-0.80,
                approved=False,
                reason=str(getattr(deployment_plan, "reason", "invalid deployment plan")),
            )

        plan = dict(getattr(deployment_plan, "deployment_plan", {}))
        kubernetes = dict(plan.get("kubernetes", {}))
        selected_resource = str(getattr(deployment_plan, "selected_resource", ""))
        if placement_decision is not None:
            selected_resource = str(
                getattr(placement_decision, "selected_resource", selected_resource)
            )

        return AgentDecision(
            agent=self.name,
            action="app_plan_deployment",
            reward=0.80,
            approved=True,
            reason=(
                "AI application deployment plan is ready for Kubernetes manifest "
                "generation and dry-run validation."
            ),
            parameters={
                "workload": str(getattr(deployment_plan, "workload", "")),
                "namespace": str(kubernetes.get("namespace", "")),
                "deployment": str(kubernetes.get("deployment", "")),
                "selected_resource": selected_resource,
            },
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

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.models import AlertEvent, Diagnosis, ScaleAction


@dataclass(frozen=True)
class AIApplicationManagementAgent:
    """Builds application-level Kubernetes control actions."""

    name: str = "AIApplicationManagementAgent"
    default_cpu_replicas: int = 3

    def propose(
        self,
        alert: AlertEvent,
        diagnosis: Diagnosis,
    ) -> tuple[ScaleAction, AgentDecision]:
        if diagnosis.cause not in _SCALING_CAUSES:
            raise ValueError(f"unsupported diagnosis for scaling: {diagnosis.cause}")

        action = ScaleAction(
            namespace=alert.namespace,
            deployment=alert.service,
            replicas=self.default_cpu_replicas,
            reason=(
                f"{diagnosis.service} {diagnosis.cause} "
                f"severity={diagnosis.severity} confidence={diagnosis.confidence:.2f}"
            ),
        )
        return action, AgentDecision(
            agent=self.name,
            action="app_scale_deployment",
            reward=0.85,
            approved=True,
            reason=(
                f"Scale {alert.service} to {self.default_cpu_replicas} replicas "
                "as the application management action."
            ),
            parameters={
                "namespace": action.namespace,
                "deployment": action.deployment,
                "replicas": str(action.replicas),
            },
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


_SCALING_CAUSES = {
    "cpu_saturation",
    "memory_saturation",
    "latency_saturation",
    "network_degradation",
    "pod_restarts",
    "low_availability",
}

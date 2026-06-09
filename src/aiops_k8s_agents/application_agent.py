from __future__ import annotations

from dataclasses import dataclass

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
        if diagnosis.cause != "cpu_saturation":
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
                f"{alert.service}를 {self.default_cpu_replicas}개 replica로 "
                "확장하는 응용 관리 액션을 제안합니다."
            ),
            parameters={
                "namespace": action.namespace,
                "deployment": action.deployment,
                "replicas": str(action.replicas),
            },
        )

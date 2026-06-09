from __future__ import annotations

from dataclasses import dataclass

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.models import ScaleAction


@dataclass(frozen=True)
class AISemiconductorInfraOpsAgent:
    """Reviews proposed actions from simulated GPU/NPU infrastructure capacity view."""

    name: str = "AISemiconductorInfraOpsAgent"
    max_recommended_replicas: int = 5

    def review(self, action: ScaleAction) -> AgentDecision:
        if action.replicas > self.max_recommended_replicas:
            return AgentDecision(
                agent=self.name,
                action="infra_capacity_rejected",
                reward=-0.60,
                approved=False,
                reason=(
                    "요청 replica 수가 AI 반도체 인프라 권장 범위를 "
                    "초과했습니다."
                ),
            )
        return AgentDecision(
            agent=self.name,
            action="infra_capacity_approved",
            reward=0.70,
            approved=True,
            reason=(
                "replica 목표가 모사 GPU/NPU 인프라 자원 범위 안에 있어 "
                "승인합니다."
            ),
        )

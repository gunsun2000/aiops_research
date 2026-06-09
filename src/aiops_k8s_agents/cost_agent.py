from __future__ import annotations

from dataclasses import dataclass

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.models import ScaleAction


@dataclass(frozen=True)
class CostOptimizationAgent:
    """Reviews whether a proposed action is acceptable from a cost policy view."""

    name: str = "CostOptimizationAgent"
    max_cost_safe_replicas: int = 3

    def review(self, action: ScaleAction) -> AgentDecision:
        if action.replicas > self.max_cost_safe_replicas:
            return AgentDecision(
                agent=self.name,
                action="cost_budget_rejected",
                reward=-0.70,
                approved=False,
                reason="요청 replica 수가 1차 비용 정책 범위를 초과했습니다.",
            )
        return AgentDecision(
            agent=self.name,
            action="cost_budget_approved",
            reward=0.60,
            approved=True,
            reason="replica 목표가 1차 비용 정책 범위 안에 있어 승인합니다.",
        )

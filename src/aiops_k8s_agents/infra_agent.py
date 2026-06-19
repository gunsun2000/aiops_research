from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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

    def review_operation(
        self,
        recovery_action: ScaleAction | None = None,
        placement_decision: Any | None = None,
    ) -> AgentDecision:
        if recovery_action is not None:
            return self.review(recovery_action)

        if placement_decision is None:
            return AgentDecision(
                agent=self.name,
                action="infra_placement_rejected",
                reward=-0.65,
                approved=False,
                reason="CPU/GPU VM placement decision is required.",
            )

        if not getattr(placement_decision, "valid", False):
            return AgentDecision(
                agent=self.name,
                action="infra_placement_rejected",
                reward=-0.65,
                approved=False,
                reason=str(getattr(placement_decision, "reason", "invalid placement")),
            )

        if not getattr(placement_decision, "slo_satisfied", False):
            return AgentDecision(
                agent=self.name,
                action="infra_slo_rejected",
                reward=-0.65,
                approved=False,
                reason="Selected CPU/GPU VM resource does not satisfy the SLO.",
            )

        return AgentDecision(
            agent=self.name,
            action="infra_placement_approved",
            reward=0.70,
            approved=True,
            reason="Selected CPU/GPU VM resource satisfies SLO and capacity constraints.",
            parameters={
                "selected_resource": str(
                    getattr(placement_decision, "selected_resource", "")
                ),
                "latency_ms": str(getattr(placement_decision, "latency_ms", "")),
                "throughput_rps": str(
                    getattr(placement_decision, "throughput_rps", "")
                ),
                "cost_per_hour": str(
                    getattr(placement_decision, "cost_per_hour", "")
                ),
            },
        )

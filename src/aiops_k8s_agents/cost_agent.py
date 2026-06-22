from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.models import RecoveryAction, RecoveryActionKind, ScaleAction


@dataclass(frozen=True)
class CostOptimizationAgent:
    """Reviews whether a proposed action is acceptable from a cost policy view."""

    name: str = "CostOptimizationAgent"
    max_cost_safe_replicas: int = 3
    max_safe_cost_per_hour: float = 2.0

    def review(self, action: ScaleAction | RecoveryAction) -> AgentDecision:
        if isinstance(action, RecoveryAction) and action.kind != RecoveryActionKind.SCALE_OUT:
            return AgentDecision(
                agent=self.name,
                action="cost_budget_approved",
                reward=0.60,
                approved=True,
                reason=(
                    f"{action.kind.value} does not increase replica count and is "
                    "within the first-stage cost policy."
                ),
                parameters={"action_kind": action.kind.value},
            )
        replicas = action.replicas
        if replicas is None:
            return AgentDecision(
                agent=self.name,
                action="cost_budget_rejected",
                reward=-0.70,
                approved=False,
                reason="scale_out requires an explicit replica target for cost review.",
            )
        if replicas > self.max_cost_safe_replicas:
            return AgentDecision(
                agent=self.name,
                action="cost_budget_rejected",
                reward=-0.70,
                approved=False,
                reason="Requested replicas exceed the first-stage cost policy.",
            )
        return AgentDecision(
            agent=self.name,
            action="cost_budget_approved",
            reward=0.60,
            approved=True,
            reason="Requested replicas are within the first-stage cost policy.",
        )

    def review_operation(
        self,
        recovery_action: ScaleAction | RecoveryAction | None = None,
        placement_decision: Any | None = None,
    ) -> AgentDecision:
        if recovery_action is not None:
            return self.review(recovery_action)

        if placement_decision is None or not getattr(placement_decision, "valid", False):
            return AgentDecision(
                agent=self.name,
                action="cost_placement_rejected",
                reward=-0.55,
                approved=False,
                reason="Valid CPU/GPU VM placement decision is required for cost review.",
            )

        cost_per_hour = float(getattr(placement_decision, "cost_per_hour", 0.0))
        if cost_per_hour > self.max_safe_cost_per_hour:
            return AgentDecision(
                agent=self.name,
                action="cost_placement_rejected",
                reward=-0.55,
                approved=False,
                reason=(
                    f"Selected resource cost {cost_per_hour:.2f}/hour exceeds "
                    f"safe policy {self.max_safe_cost_per_hour:.2f}/hour."
                ),
            )

        return AgentDecision(
            agent=self.name,
            action="cost_placement_approved",
            reward=0.55,
            approved=True,
            reason="Selected CPU/GPU VM resource is within the cost policy.",
            parameters={
                "selected_resource": str(
                    getattr(placement_decision, "selected_resource", "")
                ),
                "cost_per_hour": f"{cost_per_hour:.2f}",
            },
        )

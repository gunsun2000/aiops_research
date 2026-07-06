from __future__ import annotations

from dataclasses import dataclass
from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.models import (
    CandidateEvaluation,
    RecoveryAction,
    RecoveryActionCandidate,
    RecoveryActionKind,
    ScaleAction,
)


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

    def evaluate_candidates(
        self,
        candidates: list[RecoveryActionCandidate],
    ) -> list[CandidateEvaluation]:
        evaluations: list[CandidateEvaluation] = []
        for candidate in candidates:
            action = candidate.action
            review = self.review(action)
            if action.kind == RecoveryActionKind.OBSERVE_ONLY:
                score = 0.98
            elif action.kind == RecoveryActionKind.ROLLOUT_RESTART:
                score = 0.86
            else:
                replicas = action.replicas or 0
                score = max(0.0, 0.95 - max(replicas - 1, 0) * 0.14)
            evaluations.append(
                CandidateEvaluation(
                    agent=self.name,
                    action_kind=action.kind,
                    approved=review.approved,
                    score=score if review.approved else 0.0,
                    reward=review.reward,
                    reason=review.reason,
                    risk=candidate.risk_level,
                    blocking_reason="" if review.approved else review.reason,
                )
            )
        return evaluations

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.models import (
    CandidateEvaluation,
    RecoveryAction,
    RecoveryActionCandidate,
    RecoveryActionKind,
    ScaleAction,
)


@dataclass(frozen=True)
class AISemiconductorInfraOpsAgent:
    """Reviews proposed actions from simulated GPU/NPU infrastructure capacity view."""

    name: str = "AISemiconductorInfraOpsAgent"
    max_recommended_replicas: int = 5

    def review(self, action: ScaleAction | RecoveryAction) -> AgentDecision:
        if isinstance(action, RecoveryAction) and action.kind != RecoveryActionKind.SCALE_OUT:
            return AgentDecision(
                agent=self.name,
                action="infra_action_approved",
                reward=0.70,
                approved=True,
                reason=(
                    f"{action.kind.value} does not increase replica capacity and is "
                    "within the first-stage infrastructure policy."
                ),
                parameters={"action_kind": action.kind.value},
            )

        replicas = action.replicas
        if replicas is None:
            return AgentDecision(
                agent=self.name,
                action="infra_capacity_rejected",
                reward=-0.60,
                approved=False,
                reason="scale_out requires an explicit replica target.",
            )
        if replicas > self.max_recommended_replicas:
            return AgentDecision(
                agent=self.name,
                action="infra_capacity_rejected",
                reward=-0.60,
                approved=False,
                reason="Requested replicas exceed the first-stage infrastructure policy.",
            )
        return AgentDecision(
            agent=self.name,
            action="infra_capacity_approved",
            reward=0.70,
            approved=True,
            reason="Requested replicas are within the simulated GPU/NPU capacity policy.",
        )

    def review_operation(
        self,
        recovery_action: ScaleAction | RecoveryAction | None = None,
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

    def evaluate_candidates(
        self,
        candidates: list[RecoveryActionCandidate],
    ) -> list[CandidateEvaluation]:
        evaluations: list[CandidateEvaluation] = []
        for candidate in candidates:
            action = candidate.action
            review = self.review(action)
            score = candidate.priority
            if action.kind == RecoveryActionKind.SCALE_OUT and action.replicas:
                capacity_margin = max(self.max_recommended_replicas - action.replicas, 0)
                score = min(1.0, 0.55 + capacity_margin * 0.08)
            elif action.kind == RecoveryActionKind.ROLLOUT_RESTART:
                score = 0.82
            elif action.kind == RecoveryActionKind.OBSERVE_ONLY:
                score = 0.90
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

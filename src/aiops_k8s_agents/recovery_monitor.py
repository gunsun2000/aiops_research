from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol

from aiops_k8s_agents.evidence import EvidenceSnapshot
from aiops_k8s_agents.models import CommandResult, RecoveryAction, RecoveryActionKind


@dataclass(frozen=True)
class RecoveryAssessment:
    recovery_success: bool
    metric_improvement: float
    remaining_problem: str
    recovery_confidence: float
    replanning_required: bool

    def to_dict(self) -> dict:
        return asdict(self)


class RecoveryMonitor(Protocol):
    def assess(
        self,
        action: RecoveryAction,
        before: EvidenceSnapshot,
        after: EvidenceSnapshot,
        execution_result: CommandResult,
    ) -> RecoveryAssessment:
        """Assess whether one recovery action fixed the observed problem."""


@dataclass(frozen=True)
class FakeRecoveryMonitor:
    """Deterministic recovery monitor for mock and unit-test scenarios."""

    default_success: bool = True
    action_success: dict[RecoveryActionKind, bool] | None = None

    def assess(
        self,
        action: RecoveryAction,
        before: EvidenceSnapshot,
        after: EvidenceSnapshot,
        execution_result: CommandResult,
    ) -> RecoveryAssessment:
        del before, after
        action_success = self.action_success or {}
        success = bool(action_success.get(action.kind, self.default_success))
        if not execution_result.valid:
            success = False
        return RecoveryAssessment(
            recovery_success=success,
            metric_improvement=0.85 if success else 0.15,
            remaining_problem="" if success else f"{action.kind.value} did not recover service",
            recovery_confidence=0.90 if success else 0.35,
            replanning_required=not success,
        )

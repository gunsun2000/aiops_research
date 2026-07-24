from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Callable, Protocol

from aiops_k8s_agents.evidence import EvidenceProvider, EvidenceSnapshot
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


@dataclass(frozen=True)
class KubernetesSnapshotRecoveryMonitor:
    """Conservatively verify a real action through Kubernetes snapshots.

    This monitor verifies deployment readiness and an action-specific state
    transition. It does not claim Prometheus-level incident recovery.
    """

    evidence_provider: EvidenceProvider
    max_attempts: int = 12
    interval_seconds: float = 5.0
    sleeper: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")

    def assess(
        self,
        action: RecoveryAction,
        before: EvidenceSnapshot,
        after: EvidenceSnapshot,
        execution_result: CommandResult,
    ) -> RecoveryAssessment:
        if not execution_result.valid:
            return _failed_assessment(
                execution_result.stderr or "Kubernetes action failed"
            )

        current = after
        last_reason = "Kubernetes state transition was not observed"
        improvement = 0.0
        for attempt in range(self.max_attempts):
            ready, last_reason = _snapshot_transition_ready(
                action,
                before,
                current,
            )
            improvement = _availability_improvement(before, current)
            if ready:
                return RecoveryAssessment(
                    recovery_success=True,
                    metric_improvement=improvement,
                    remaining_problem="",
                    recovery_confidence=0.85,
                    replanning_required=False,
                )
            if attempt + 1 < self.max_attempts:
                self.sleeper(self.interval_seconds)
                current = self.evidence_provider.collect(
                    action.namespace,
                    action.deployment,
                )

        return RecoveryAssessment(
            recovery_success=False,
            metric_improvement=improvement,
            remaining_problem=last_reason,
            recovery_confidence=0.35,
            replanning_required=True,
        )


def _snapshot_transition_ready(
    action: RecoveryAction,
    before: EvidenceSnapshot,
    after: EvidenceSnapshot,
) -> tuple[bool, str]:
    desired = after.desired_replicas
    available = after.available_replicas
    if desired < 1:
        return False, "deployment has no desired replicas"
    if available < desired:
        return (
            False,
            f"available replicas {available} remain below desired replicas {desired}",
        )
    if any(status not in {"Running", "Succeeded"} for status in after.pod_statuses):
        return False, "one or more pods are not in a ready running state"

    if action.kind == RecoveryActionKind.SCALE_OUT:
        if action.replicas is None or desired != action.replicas:
            return False, "deployment did not reach the validated scale target"
        if desired <= before.desired_replicas:
            return False, "scale_out did not increase desired replicas"
        return True, ""

    before_ids = set(before.pod_identities)
    after_ids = set(after.pod_identities)
    workload_changed = bool(after_ids and before_ids != after_ids)
    availability_improved = available > before.available_replicas
    if action.kind == RecoveryActionKind.ROLLOUT_RESTART:
        if not workload_changed:
            return False, "rollout restart has not produced a new pod identity"
        return True, ""
    if action.kind == RecoveryActionKind.OBSERVE_ONLY:
        if not (workload_changed or availability_improved):
            return False, "observation found no verifiable recovery state change"
        return True, ""
    return False, "unsupported recovery action"


def _availability_improvement(
    before: EvidenceSnapshot,
    after: EvidenceSnapshot,
) -> float:
    before_ratio = before.available_replicas / max(before.desired_replicas, 1)
    after_ratio = after.available_replicas / max(after.desired_replicas, 1)
    replica_gain = max(
        after.available_replicas - before.available_replicas,
        0,
    ) / max(after.desired_replicas, 1)
    return round(min(max(after_ratio - before_ratio, replica_gain, 0.0), 1.0), 6)


def _failed_assessment(reason: str) -> RecoveryAssessment:
    return RecoveryAssessment(
        recovery_success=False,
        metric_improvement=0.0,
        remaining_problem=reason,
        recovery_confidence=0.20,
        replanning_required=True,
    )

from aiops_k8s_agents.evidence import EvidenceSnapshot, FakeEvidenceProvider
from aiops_k8s_agents.models import (
    CommandResult,
    RecoveryAction,
    RecoveryActionKind,
)
from aiops_k8s_agents.recovery_monitor import (
    KubernetesSnapshotRecoveryMonitor,
)


def test_kubernetes_snapshot_monitor_requires_ready_target_state():
    action = RecoveryAction(
        namespace="online-boutique",
        deployment="paymentservice",
        kind=RecoveryActionKind.SCALE_OUT,
        replicas=3,
    )
    before = _snapshot(desired=1, available=1)
    provider = FakeEvidenceProvider(_snapshot(desired=3, available=2))
    monitor = KubernetesSnapshotRecoveryMonitor(
        evidence_provider=provider,
        max_attempts=1,
        interval_seconds=0,
    )

    result = monitor.assess(
        action,
        before,
        provider.collect(action.namespace, action.deployment),
        _execution(valid=True),
    )

    assert result.recovery_success is False
    assert result.replanning_required is True
    assert "available replicas" in result.remaining_problem


def test_kubernetes_snapshot_monitor_accepts_ready_scaled_deployment():
    action = RecoveryAction(
        namespace="online-boutique",
        deployment="paymentservice",
        kind=RecoveryActionKind.SCALE_OUT,
        replicas=3,
    )
    before = _snapshot(desired=1, available=1)
    provider = FakeEvidenceProvider(_snapshot(desired=3, available=3))
    monitor = KubernetesSnapshotRecoveryMonitor(
        evidence_provider=provider,
        max_attempts=1,
        interval_seconds=0,
    )

    result = monitor.assess(
        action,
        before,
        provider.collect(action.namespace, action.deployment),
        _execution(valid=True),
    )

    assert result.recovery_success is True
    assert result.replanning_required is False
    assert result.recovery_confidence >= 0.8


def _snapshot(*, desired: int, available: int) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        namespace="online-boutique",
        deployment="paymentservice",
        desired_replicas=desired,
        available_replicas=available,
        pod_statuses=("Running",),
        source="kubernetes",
    )


def _execution(*, valid: bool) -> CommandResult:
    return CommandResult(
        command="kubectl scale deployment paymentservice --replicas=3",
        mode="real",
        valid=valid,
        stdout="scaled" if valid else "",
        stderr="" if valid else "failed",
    )

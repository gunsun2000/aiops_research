from dataclasses import replace

import pytest

from aiops_k8s_agents.cost_agent import CostOptimizationAgent
from aiops_k8s_agents.evidence import EvidenceSnapshot, FakeEvidenceProvider
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.infra_agent import AISemiconductorInfraOpsAgent
import aiops_k8s_agents.mutual_supervision as mutual_supervision_module
from aiops_k8s_agents.models import CommandResult, RecoveryActionKind
from aiops_k8s_agents.mutual_supervision import MutualSupervisionCoordinator
from aiops_k8s_agents.mutual_supervision_policy import (
    load_mutual_supervision_policy,
)
from aiops_k8s_agents.recovery_monitor import FakeRecoveryMonitor
from aiops_k8s_agents.operation_lock import TargetOperationLock
from aiops_k8s_agents.research_event_store import InMemoryResearchEventStore
from aiops_k8s_agents.validator import CommandValidator


def test_cost_agent_revision_changes_replica_target_before_execution():
    coordinator = _coordinator(
        cost_agent=CostOptimizationAgent(max_cost_safe_replicas=2),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["valid"] is True
    assert report["final_status"] == "recovered"
    assert report["selected_action"]["kind"] == "scale_out"
    assert report["selected_action"]["replicas"] == 2
    assert report["negotiation"]["round_count"] == 2
    assert any(
        review["verdict"] == "revise"
        and review["reviewer"] == "CostOptimizationAgent"
        for review in report["peer_reviews"]
    )


def test_cost_revision_never_turns_scale_out_into_scale_down():
    coordinator = MutualSupervisionCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
            desired_replicas=4,
            available_replicas=4,
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.MOCK,
        policy=_policy(),
        cost_agent=CostOptimizationAgent(max_cost_safe_replicas=3),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["valid"] is False
    assert report["final_status"] == "safe_stopped"
    assert report["executed_actions"] == []
    assert report["execution_result"]["command"] == ""
    assert any(
        review["verdict"] == "veto"
        and review["reviewer"] == "CostOptimizationAgent"
        for review in report["peer_reviews"]
    )


def test_infrastructure_veto_blocks_unsafe_scale_out():
    policy = replace(_policy(), max_negotiation_rounds=1)
    coordinator = _coordinator(
        policy=policy,
        infra_agent=AISemiconductorInfraOpsAgent(max_recommended_replicas=1),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["valid"] is False
    assert report["final_status"] == "safe_stopped"
    assert report["selected_action"] == {}
    assert report["execution_result"]["command"] == ""
    assert report["executed_actions"] == []
    assert report["human_review_required"] is True
    assert any(
        review["verdict"] == "veto"
        and review["reviewer"] == "AISemiconductorInfraOpsAgent"
        for review in report["peer_reviews"]
    )


def test_unknown_metric_safely_finishes_without_negotiation_or_execution():
    coordinator = MutualSupervisionCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider(
            EvidenceSnapshot(
                namespace="online-boutique",
                deployment="paymentservice",
                metric_values={"queue_depth": 95.0},
                desired_replicas=1,
                available_replicas=1,
            )
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.MOCK,
        policy=_policy(),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="queue_depth",
        threshold=80.0,
    )

    assert report["valid"] is False
    assert report["final_status"] == "no_action_required"
    assert report["diagnosis"]["cause"] == "unknown_metric"
    assert report["peer_reviews"] == []
    assert report["executed_actions"] == []
    assert report["human_review_required"] is False


def test_application_action_receives_all_required_peer_reviews():
    coordinator = _coordinator()

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    reviewers = {
        review["reviewer"]
        for review in report["peer_reviews"]
        if review["round_index"] == 1
        and review["target_agent"] == "AIApplicationManagementAgent"
    }

    assert reviewers == {
        "AIServiceHASupportAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    }
    assert report["negotiation"]["consensus"] == "approved"


def test_validation_failure_never_appears_in_executed_actions():
    coordinator = MutualSupervisionCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"checkoutservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            "online-boutique", "paymentservice", 95.0
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.MOCK,
        policy=_policy(),
    )

    report = coordinator.run(
        "online-boutique", "paymentservice", "cpu", 80.0
    )

    assert report["valid"] is False
    assert report["safety_validation"]["valid"] is False
    assert report["execution_result"]["command"] == ""
    assert report["executed_actions"] == []
    assert report["human_review_required"] is True


def test_failed_recovery_replans_to_next_bounded_candidate():
    coordinator = MutualSupervisionCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            "online-boutique", "paymentservice", 95.0
        ),
        recovery_monitor=FakeRecoveryMonitor(
            action_success={
                RecoveryActionKind.SCALE_OUT: False,
                RecoveryActionKind.ROLLOUT_RESTART: True,
            }
        ),
        mode=ExecutionMode.MOCK,
        policy=_policy(),
    )

    report = coordinator.run(
        "online-boutique", "paymentservice", "cpu", 80.0
    )

    assert report["valid"] is True
    assert report["final_status"] == "recovered_after_replan"
    assert [action["kind"] for action in report["executed_actions"]] == [
        "scale_out",
        "rollout_restart",
    ]
    assert report["selected_action"]["kind"] == "rollout_restart"
    assert len(report["replanning_attempts"]) == 1


def test_successful_execution_receives_four_role_specific_post_reviews():
    coordinator = _coordinator()

    report = coordinator.run(
        "online-boutique", "paymentservice", "cpu", 80.0
    )

    assert len(report["post_execution_reviews"]) == 4
    assert {
        review["agent"] for review in report["post_execution_reviews"]
    } == {
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    }
    assert all(
        review["approved"] for review in report["post_execution_reviews"]
    )


def test_coordinator_persists_complete_mutual_supervision_trace():
    event_store = InMemoryResearchEventStore()
    coordinator = _coordinator(event_store=event_store)

    report = coordinator.run(
        "online-boutique", "paymentservice", "cpu", 80.0
    )

    assert event_store.final_report["run_id"] == report["run_id"]
    assert len(event_store.events["evidence"]) == 1
    assert len(event_store.events["initial_decisions"]) >= 2
    assert len(event_store.events["peer_reviews"]) >= 3
    assert len(event_store.events["negotiation_rounds"]) >= 1
    assert len(event_store.events["safety_validations"]) == 1
    assert [
        event["event_type"]
        for event in event_store.events["executed_actions"]
    ] == ["execution_dispatched", "execution_completed"]
    assert len(event_store.events["post_execution_reviews"]) == 4


def test_event_store_keeps_pre_execution_trace_when_executor_crashes(monkeypatch):
    event_store = InMemoryResearchEventStore()
    coordinator = _coordinator(event_store=event_store)

    def crash_during_execution(*_args, **_kwargs):
        raise RuntimeError("simulated executor crash")

    monkeypatch.setattr(
        mutual_supervision_module.KubernetesExecutor,
        "execute_recovery",
        crash_during_execution,
    )

    with pytest.raises(RuntimeError, match="simulated executor crash"):
        coordinator.run(
            "online-boutique", "paymentservice", "cpu", 80.0
        )

    assert len(event_store.events["evidence"]) == 1
    assert len(event_store.events["initial_decisions"]) >= 2
    assert len(event_store.events["peer_reviews"]) >= 3
    assert len(event_store.events["negotiation_rounds"]) >= 1
    assert len(event_store.events["safety_validations"]) == 1
    assert len(event_store.events["executed_actions"]) == 1
    assert (
        event_store.events["executed_actions"][0]["event_type"]
        == "execution_dispatched"
    )


def test_failed_execution_result_is_persisted_before_replanning(monkeypatch):
    event_store = InMemoryResearchEventStore()
    coordinator = _coordinator(
        event_store=event_store,
        policy=replace(_policy(), max_replan_attempts=0),
    )

    def reject_execution(_executor, action):
        return CommandResult(
            command=f"rejected {action.kind.value}",
            mode="mock",
            valid=False,
            stdout="",
            stderr="simulated command rejection",
        )

    monkeypatch.setattr(
        mutual_supervision_module.KubernetesExecutor,
        "execute_recovery",
        reject_execution,
    )

    report = coordinator.run(
        "online-boutique", "paymentservice", "cpu", 80.0
    )

    assert report["valid"] is False
    assert len(event_store.events["executed_actions"]) == 2
    assert (
        event_store.events["executed_actions"][0]["event_type"]
        == "execution_dispatched"
    )
    persisted = event_store.events["executed_actions"][1]
    assert persisted["event_type"] == "execution_completed"
    assert persisted["action"]["kind"] == "scale_out"
    assert persisted["execution_result"]["valid"] is False
    assert persisted["execution_result"]["stderr"] == "simulated command rejection"


def test_real_coordinator_safely_stops_when_target_lock_is_held(tmp_path):
    coordinator = MutualSupervisionCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.REAL,
        policy=_policy(),
        operation_lock_dir=tmp_path,
    )

    with TargetOperationLock(
        namespace="online-boutique",
        deployment="paymentservice",
        lock_dir=tmp_path,
    ):
        report = coordinator.run(
            "online-boutique", "paymentservice", "cpu", 80.0
        )

    assert report["valid"] is False
    assert report["final_status"] == "safe_stopped"
    assert report["executed_actions"] == []
    assert "already active" in report["execution_result"]["stderr"]
    assert report["human_review_required"] is True


def _coordinator(
    *,
    policy=None,
    infra_agent=None,
    cost_agent=None,
    event_store=None,
) -> MutualSupervisionCoordinator:
    return MutualSupervisionCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.MOCK,
        policy=policy or _policy(),
        infra_agent=infra_agent or AISemiconductorInfraOpsAgent(),
        cost_agent=cost_agent or CostOptimizationAgent(),
        event_store=event_store,
    )


def _policy():
    return load_mutual_supervision_policy(
        "config/mutual_supervision_policy.json"
    )


def _validator() -> CommandValidator:
    return CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
        min_replicas=1,
        max_replicas=5,
    )

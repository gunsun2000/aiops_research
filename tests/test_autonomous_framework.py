from aiops_k8s_agents.autonomous import AutonomousAIOpsCoordinator
from aiops_k8s_agents.evidence import EvidenceSnapshot, FakeEvidenceProvider
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.ha_agent import AIServiceHASupportAgent
from aiops_k8s_agents.models import RecoveryActionKind
from aiops_k8s_agents.recovery_monitor import FakeRecoveryMonitor
from aiops_k8s_agents.validator import CommandValidator


def _validator() -> CommandValidator:
    return CommandValidator(
        allowed_namespaces={"online-boutique"},
        allowed_deployments={"paymentservice"},
        min_replicas=1,
        max_replicas=5,
    )


def test_fake_evidence_provider_returns_operational_snapshot():
    provider = FakeEvidenceProvider.cpu_saturation(
        namespace="online-boutique",
        deployment="paymentservice",
        value=95.0,
    )

    evidence = provider.collect("online-boutique", "paymentservice")

    assert evidence.source == "fake"
    assert evidence.metric_values["cpu"] == 95.0
    assert evidence.desired_replicas == 1
    assert evidence.available_replicas == 1
    assert evidence.restart_count == 0
    assert evidence.to_summary()["metric_values"]["cpu"] == 95.0


def test_autonomous_coordinator_collects_evidence_and_selects_safe_candidate():
    coordinator = AutonomousAIOpsCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.MOCK,
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["command"] == "autonomous-run"
    assert report["valid"] is True
    assert report["final_status"] == "recovered"
    assert report["diagnosis"]["cause"] == "cpu_saturation"
    assert {candidate["action"]["kind"] for candidate in report["generated_candidates"]} == {
        "observe_only",
        "rollout_restart",
        "scale_out",
    }
    assert report["selected_action"]["kind"] == "scale_out"
    assert report["selected_action"]["state_changed"] is True
    assert report["selected_action"]["action_effect_type"] == "kubernetes_state_change"
    assert report["validation_result"]["valid"] is True
    assert report["execution_result"]["command"] == (
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
    )
    assert report["recovery_monitoring"]["recovery_success"] is True


def test_high_is_bad_metric_comparison_reflects_exceeded_and_normal_cases():
    agent = AIServiceHASupportAgent()

    high_diagnosis, high_decision = agent.diagnose_evidence(
        evidence=EvidenceSnapshot(
            namespace="online-boutique",
            deployment="paymentservice",
            metric_values={"cpu": 95.0},
            desired_replicas=1,
            available_replicas=1,
        ),
        metric="cpu",
        threshold=80.0,
    )
    normal_diagnosis, normal_decision = agent.diagnose_evidence(
        evidence=EvidenceSnapshot(
            namespace="online-boutique",
            deployment="paymentservice",
            metric_values={"cpu": 50.0},
            desired_replicas=1,
            available_replicas=1,
        ),
        metric="cpu",
        threshold=80.0,
    )

    assert high_diagnosis.evidence["threshold_comparison"] == "95.000 >= 80.000"
    assert high_diagnosis.evidence["threshold_exceeded"] is True
    assert high_decision.approved is True
    assert normal_diagnosis.evidence["threshold_comparison"] == "50.000 < 80.000"
    assert normal_diagnosis.evidence["threshold_exceeded"] is False
    assert normal_decision.approved is False


def test_autonomous_coordinator_replans_after_failed_first_action():
    coordinator = AutonomousAIOpsCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider(
            EvidenceSnapshot(
                namespace="online-boutique",
                deployment="paymentservice",
                metric_values={"restart_count": 3.0},
                desired_replicas=1,
                available_replicas=1,
                restart_count=3,
                events=("BackOff restarting failed container",),
            )
        ),
        recovery_monitor=FakeRecoveryMonitor(
            action_success={
                RecoveryActionKind.ROLLOUT_RESTART: False,
                RecoveryActionKind.OBSERVE_ONLY: True,
            }
        ),
        mode=ExecutionMode.MOCK,
        max_replan_attempts=2,
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="restart_count",
        threshold=1.0,
    )

    assert report["valid"] is True
    assert report["final_status"] == "recovered_after_replan"
    assert len(report["replanning_attempts"]) == 1
    assert report["executed_actions"][0]["kind"] == "rollout_restart"
    assert report["executed_actions"][1]["kind"] == "observe_only"
    assert report["executed_actions"][1]["state_changed"] is False
    assert (
        report["executed_actions"][1]["action_effect_type"]
        == "read_only_observation"
    )
    assert report["policy_update_recommendations"][0]["requires_human_review"] is True


def test_autonomous_coordinator_safe_terminates_after_replan_limit():
    coordinator = AutonomousAIOpsCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=False),
        mode=ExecutionMode.MOCK,
        max_replan_attempts=1,
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["valid"] is False
    assert report["final_status"] == "safe_failure"
    assert len(report["executed_actions"]) == 2
    assert report["recovery_monitoring"]["replanning_required"] is True


def test_unknown_evidence_metric_does_not_fallback_to_cpu_saturation():
    agent = AIServiceHASupportAgent()
    evidence = EvidenceSnapshot(
        namespace="online-boutique",
        deployment="paymentservice",
        metric_values={"queue_depth": 95.0},
        desired_replicas=1,
        available_replicas=1,
    )

    diagnosis, decision = agent.diagnose_evidence(
        evidence=evidence,
        metric="queue_depth",
        threshold=80.0,
    )

    assert diagnosis.cause == "unknown_metric"
    assert diagnosis.cause != "cpu_saturation"
    assert diagnosis.evidence["preferred_action"] == "observe_only"
    assert decision.approved is False
    assert decision.action == "ha_no_action"


def test_autonomous_unknown_metric_observes_without_scale_out():
    coordinator = AutonomousAIOpsCoordinator(
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
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="queue_depth",
        threshold=80.0,
    )

    assert report["valid"] is False
    assert report["diagnosis"]["cause"] == "unknown_metric"
    assert report["final_status"] == "no_action_required"
    assert report["generated_candidates"] == []
    assert report["executed_actions"] == []


def test_low_is_bad_availability_below_threshold_diagnoses_low_availability():
    agent = AIServiceHASupportAgent()
    evidence = EvidenceSnapshot(
        namespace="online-boutique",
        deployment="paymentservice",
        metric_values={"availability": 0.60},
        desired_replicas=1,
        available_replicas=1,
    )

    diagnosis, decision = agent.diagnose_evidence(
        evidence=evidence,
        metric="availability",
        threshold=0.90,
    )

    assert diagnosis.cause == "low_availability"
    assert diagnosis.severity in {"warning", "critical"}
    assert diagnosis.evidence["threshold_comparison"] == "0.600 <= 0.900"
    assert diagnosis.evidence["threshold_exceeded"] is True
    assert decision.approved is True


def test_low_is_bad_availability_at_threshold_does_not_select_risky_action():
    coordinator = AutonomousAIOpsCoordinator(
        validator=_validator(),
        evidence_provider=FakeEvidenceProvider(
            EvidenceSnapshot(
                namespace="online-boutique",
                deployment="paymentservice",
                metric_values={"availability": 0.95},
                desired_replicas=1,
                available_replicas=1,
            )
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.MOCK,
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="availability",
        threshold=0.90,
    )

    assert report["valid"] is False
    assert report["final_status"] == "no_action_required"
    assert report["diagnosis"]["evidence"]["threshold_comparison"] == "0.950 > 0.900"
    assert report["diagnosis"]["evidence"]["threshold_exceeded"] is False
    assert report["executed_actions"] == []


def test_autonomous_rejects_disallowed_deployment_without_executing_action():
    coordinator = AutonomousAIOpsCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"checkoutservice"},
            min_replicas=1,
            max_replicas=1,
        ),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(default_success=True),
        mode=ExecutionMode.MOCK,
        max_replan_attempts=0,
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["valid"] is False
    assert report["final_status"] == "safe_failure"
    assert report["validation_result"]["valid"] is False
    assert "not allowlisted" in report["validation_result"]["stderr"]
    assert report["executed_actions"] == []
    assert report["policy_update_recommendations"][0]["requires_human_review"] is True

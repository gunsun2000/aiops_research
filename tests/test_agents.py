from aiops_k8s_agents.agents import AIMCMPCoordinator, CostOptimizationAgent
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.models import AlertEvent
from aiops_k8s_agents.validator import CommandValidator


def test_cpu_alert_coordinator_generates_paymentservice_scale_action():
    coordinator = AIMCMPCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.MOCK,
    )
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu",
        value=95.0,
        threshold=80.0,
        message="Prometheus alert: paymentservice CPU is above 95%",
    )

    result = coordinator.run(alert)

    assert result.valid is True
    assert result.mode == "mock"
    assert result.command == (
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
    )
    assert result.metadata["coordinator"] == "AI-MCMP"
    assert result.metadata["consensus"] == "approved"
    assert result.metadata["agents"] == (
        "AIServiceHASupportAgent,"
        "AIApplicationManagementAgent,"
        "AISemiconductorInfraOpsAgent,"
        "CostOptimizationAgent"
    )
    assert result.metadata["actions"] == (
        "AIServiceHASupportAgent:ha_scale_out_required|"
        "AIApplicationManagementAgent:app_scale_deployment|"
        "AISemiconductorInfraOpsAgent:infra_capacity_approved|"
        "CostOptimizationAgent:cost_budget_approved"
    )
    assert result.metadata["rewards"] == (
        "AIServiceHASupportAgent:0.90|"
        "AIApplicationManagementAgent:0.85|"
        "AISemiconductorInfraOpsAgent:0.70|"
        "CostOptimizationAgent:0.60"
    )
    assert result.metadata["reward_total"] == "3.05"


def test_cpu_alert_coordinator_is_deterministic_for_acceptance_loop():
    coordinator = AIMCMPCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.MOCK,
    )
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu",
        value=95.0,
        threshold=80.0,
        message="Prometheus alert: paymentservice CPU is above 95%",
    )

    results = [coordinator.run(alert) for _ in range(10)]

    assert all(result.valid for result in results)
    assert {result.command for result in results} == {
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
    }


def test_coordinator_blocks_action_when_cross_validation_rejects_it():
    coordinator = AIMCMPCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.MOCK,
    )
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu",
        value=70.0,
        threshold=80.0,
        message="Prometheus alert: paymentservice CPU is below threshold",
    )

    result = coordinator.run(alert)

    assert result.valid is False
    assert result.command == ""
    assert result.metadata["consensus"] == "rejected"
    assert result.metadata["actions"] == "AIServiceHASupportAgent:ha_no_action"
    assert result.metadata["rewards"] == "AIServiceHASupportAgent:0.20"
    assert result.metadata["reward_total"] == "0.20"


def test_coordinator_records_negative_reward_when_cost_policy_blocks_action():
    coordinator = AIMCMPCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.MOCK,
        cost_agent=CostOptimizationAgent(max_cost_safe_replicas=2),
    )
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu",
        value=95.0,
        threshold=80.0,
        message="Prometheus 알람: paymentservice CPU가 95%를 초과했습니다",
    )

    result = coordinator.run(alert)

    assert result.valid is False
    assert result.metadata["consensus"] == "rejected"
    assert "CostOptimizationAgent:cost_budget_rejected" in result.metadata["actions"]
    assert "CostOptimizationAgent:-0.70" in result.metadata["rewards"]
    assert result.metadata["reward_total"] == "1.75"

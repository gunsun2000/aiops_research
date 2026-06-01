import asyncio
import json

from aiops_k8s_agents.autogen_groupchat import (
    AutoGenGroupChatCoordinator,
    parse_autogen_decision,
)
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.models import AlertEvent
from aiops_k8s_agents.validator import CommandValidator


def test_parse_autogen_decision_payload_with_action_reward_and_parameters():
    payload = json.dumps(
        {
            "agent": "AIApplicationManagementAgent",
            "action": "app_scale_deployment",
            "reward": 0.85,
            "approved": True,
            "reason": "CPU saturation 완화를 위해 scale-out을 제안합니다.",
            "parameters": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "replicas": 3,
            },
        }
    )

    decision = parse_autogen_decision(payload, expected_agent="AIApplicationManagementAgent")

    assert decision.agent == "AIApplicationManagementAgent"
    assert decision.action == "app_scale_deployment"
    assert decision.reward == 0.85
    assert decision.approved is True
    assert decision.parameters == {
        "namespace": "online-boutique",
        "deployment": "paymentservice",
        "replicas": "3",
    }


def test_autogen_groupchat_coordinator_executes_valid_groupchat_decisions():
    async def fake_groupchat(_alert):
        return [
            parse_autogen_decision(
                {
                    "agent": "AIServiceHASupportAgent",
                    "action": "ha_scale_out_required",
                    "reward": 0.90,
                    "approved": True,
                    "reason": "HA 관점에서 scale-out이 필요합니다.",
                },
                expected_agent="AIServiceHASupportAgent",
            ),
            parse_autogen_decision(
                {
                    "agent": "AIApplicationManagementAgent",
                    "action": "app_scale_deployment",
                    "reward": 0.85,
                    "approved": True,
                    "reason": "paymentservice를 3개 replica로 확장합니다.",
                    "parameters": {
                        "namespace": "online-boutique",
                        "deployment": "paymentservice",
                        "replicas": 3,
                    },
                },
                expected_agent="AIApplicationManagementAgent",
            ),
            parse_autogen_decision(
                {
                    "agent": "AISemiconductorInfraOpsAgent",
                    "action": "infra_capacity_approved",
                    "reward": 0.70,
                    "approved": True,
                    "reason": "인프라 자원 범위 안입니다.",
                },
                expected_agent="AISemiconductorInfraOpsAgent",
            ),
            parse_autogen_decision(
                {
                    "agent": "CostOptimizationAgent",
                    "action": "cost_budget_approved",
                    "reward": 0.60,
                    "approved": True,
                    "reason": "비용 정책 범위 안입니다.",
                },
                expected_agent="CostOptimizationAgent",
            ),
        ]

    coordinator = AutoGenGroupChatCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.MOCK,
        decision_provider=fake_groupchat,
    )
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu",
        value=95.0,
        threshold=80.0,
        message="Prometheus 알람: paymentservice CPU가 95%를 초과했습니다",
    )

    result = asyncio.run(coordinator.run(alert))

    assert result.valid is True
    assert result.command == (
        "kubectl scale deployment paymentservice --replicas=3 -n online-boutique"
    )
    assert result.metadata["coordinator"] == "AI-MCMP"
    assert result.metadata["autogen"] == "groupchat"
    assert result.metadata["reward_total"] == "3.05"


def test_autogen_groupchat_coordinator_rejects_when_one_agent_rejects():
    async def fake_groupchat(_alert):
        return [
            parse_autogen_decision(
                {
                    "agent": "AIServiceHASupportAgent",
                    "action": "ha_scale_out_required",
                    "reward": 0.90,
                    "approved": True,
                    "reason": "HA 관점에서 scale-out이 필요합니다.",
                },
                expected_agent="AIServiceHASupportAgent",
            ),
            parse_autogen_decision(
                {
                    "agent": "AIApplicationManagementAgent",
                    "action": "app_scale_deployment",
                    "reward": 0.85,
                    "approved": True,
                    "reason": "paymentservice를 3개 replica로 확장합니다.",
                    "parameters": {
                        "namespace": "online-boutique",
                        "deployment": "paymentservice",
                        "replicas": 3,
                    },
                },
                expected_agent="AIApplicationManagementAgent",
            ),
            parse_autogen_decision(
                {
                    "agent": "AISemiconductorInfraOpsAgent",
                    "action": "infra_capacity_approved",
                    "reward": 0.70,
                    "approved": True,
                    "reason": "인프라 자원 범위 안입니다.",
                },
                expected_agent="AISemiconductorInfraOpsAgent",
            ),
            parse_autogen_decision(
                {
                    "agent": "CostOptimizationAgent",
                    "action": "cost_budget_rejected",
                    "reward": -0.70,
                    "approved": False,
                    "reason": "비용 정책을 초과합니다.",
                },
                expected_agent="CostOptimizationAgent",
            ),
        ]

    coordinator = AutoGenGroupChatCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        mode=ExecutionMode.MOCK,
        decision_provider=fake_groupchat,
    )
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu",
        value=95.0,
        threshold=80.0,
        message="Prometheus 알람: paymentservice CPU가 95%를 초과했습니다",
    )

    result = asyncio.run(coordinator.run(alert))

    assert result.valid is False
    assert result.command == ""
    assert result.metadata["consensus"] == "rejected"
    assert result.metadata["reward_total"] == "1.75"

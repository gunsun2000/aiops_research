import asyncio
import builtins
import json
import sys
import types

import pytest

import aiops_k8s_agents.autogen_groupchat as autogen_groupchat
from aiops_k8s_agents.autogen_groupchat import (
    AUTOGEN_AGENT_NAMES,
    AutoGenGroupChatCoordinator,
    AutoGenRoundRobinDecisionProvider,
    _decision_schema,
    parse_autogen_decision,
)
from aiops_k8s_agents.agent_registry import AgentRegistryError
from aiops_k8s_agents.evidence import EvidenceSnapshot, FakeEvidenceProvider
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.models import AlertEvent
from aiops_k8s_agents.mutual_supervision import MutualSupervisionCoordinator
from aiops_k8s_agents.recovery_monitor import FakeRecoveryMonitor
from aiops_k8s_agents.research_protocol import (
    ResearchProtocolProfile,
    load_research_protocol,
)
from aiops_k8s_agents.validator import CommandValidationError
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


def test_parse_autogen_decision_accepts_known_agent_alias_from_llm():
    payload = {
        "agent": "AI HA Agent",
        "action": "ha_scale_out_required",
        "reward": 0.90,
        "approved": True,
        "reason": "CPU saturation requires scale-out.",
        "parameters": {
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "replicas": "3",
        },
    }

    decision = parse_autogen_decision(
        payload,
        expected_agent="AIServiceHASupportAgent",
    )

    assert decision.agent == "AIServiceHASupportAgent"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "agent": "AIServiceHASupportAgent",
            "action": "ha_scale_out_required",
            "reward": 0.9,
            "approved": "true",
            "reason": "Boolean strings must not be accepted.",
            "parameters": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "replicas": "3",
            },
        },
        {
            "agent": "AIServiceHASupportAgent",
            "action": "ha_scale_out_required",
            "reward": 0.9,
            "approved": True,
            "reason": "Unknown fields must not be accepted.",
            "parameters": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "replicas": "3",
            },
            "command": "kubectl delete pod unsafe",
        },
        {
            "agent": "AIServiceHASupportAgent",
            "action": "ha_scale_out_required",
            "reward": 0.9,
            "approved": True,
            "reason": "Unknown parameter fields must not be accepted.",
            "parameters": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "replicas": "3",
                "command": "kubectl delete pod unsafe",
            },
        },
        {
            "agent": "AIServiceHASupportAgent",
            "action": "delete_everything",
            "reward": 0.9,
            "approved": True,
            "reason": "Unknown role actions must not be accepted.",
            "parameters": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "replicas": "3",
            },
        },
    ],
)
def test_parse_autogen_decision_rejects_malformed_schema(payload):
    with pytest.raises(autogen_groupchat.AutoGenDecisionError):
        parse_autogen_decision(
            payload,
            expected_agent="AIServiceHASupportAgent",
        )


def test_autogen_action_approval_semantics_are_authoritative_per_agent():
    assert autogen_groupchat.AUTOGEN_ACTION_APPROVAL == {
        "AIServiceHASupportAgent": {
            "ha_scale_out_required": True,
            "ha_recovery_required": True,
            "ha_no_action": False,
        },
        "AIApplicationManagementAgent": {
            "app_observe_only": True,
            "app_rollout_restart": True,
            "app_scale_deployment": True,
        },
        "AISemiconductorInfraOpsAgent": {
            "infra_capacity_approved": True,
            "infra_capacity_rejected": False,
        },
        "CostOptimizationAgent": {
            "cost_budget_approved": True,
            "cost_budget_rejected": False,
        },
    }


@pytest.mark.parametrize(
    ("agent", "action", "contradictory_approved"),
    [
        ("AIServiceHASupportAgent", "ha_scale_out_required", False),
        ("AIServiceHASupportAgent", "ha_recovery_required", False),
        ("AIServiceHASupportAgent", "ha_no_action", True),
        ("AIApplicationManagementAgent", "app_observe_only", False),
        ("AIApplicationManagementAgent", "app_rollout_restart", False),
        ("AIApplicationManagementAgent", "app_scale_deployment", False),
        ("AISemiconductorInfraOpsAgent", "infra_capacity_approved", False),
        ("AISemiconductorInfraOpsAgent", "infra_capacity_rejected", True),
        ("CostOptimizationAgent", "cost_budget_approved", False),
        ("CostOptimizationAgent", "cost_budget_rejected", True),
    ],
)
def test_parse_autogen_decision_rejects_contradictory_action_approval_pairs(
    agent,
    action,
    contradictory_approved,
):
    with pytest.raises(
        autogen_groupchat.AutoGenDecisionError,
        match="contradicts",
    ):
        parse_autogen_decision(
            {
                "agent": agent,
                "action": action,
                "reward": 0.5,
                "approved": contradictory_approved,
                "reason": "Contradictory structured output must fail closed.",
            },
            expected_agent=agent,
        )


def test_decision_schema_is_strict_openai_response_format_compatible():
    schema = _decision_schema().model_json_schema()

    assert set(schema["required"]) == set(schema["properties"])
    parameters_ref = schema["properties"]["parameters"]["$ref"]
    parameters_schema_name = parameters_ref.rsplit("/", 1)[-1]
    parameters_schema = schema["$defs"][parameters_schema_name]
    assert set(parameters_schema["required"]) == set(parameters_schema["properties"])
    assert set(parameters_schema["properties"]) == {
        "namespace",
        "deployment",
        "replicas",
    }


def test_round_robin_groupchat_registers_structured_message_type():
    from autogen_agentchat.messages import StructuredMessage

    provider = AutoGenRoundRobinDecisionProvider(model_client=object())
    team = provider._build_team()

    assert team._message_factory.is_registered(StructuredMessage[_decision_schema()])


def test_round_robin_groupchat_allows_task_plus_all_agent_replies():
    provider = AutoGenRoundRobinDecisionProvider(model_client=object())
    team = provider._build_team()

    assert team._termination_condition._max_messages == len(AUTOGEN_AGENT_NAMES) + 1


def test_create_openai_model_client_supplies_model_info_for_gpt55(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_module = types.ModuleType("autogen_ext.models.openai")
    fake_module.OpenAIChatCompletionClient = FakeClient
    monkeypatch.setitem(sys.modules, "autogen_ext.models.openai", fake_module)

    client = autogen_groupchat.create_openai_model_client("gpt-5.5")

    assert isinstance(client, FakeClient)
    assert captured["model"] == "gpt-5.5"
    assert captured["model_info"] == {
        "vision": False,
        "function_calling": True,
        "json_output": True,
        "family": "gpt-5",
        "structured_output": True,
    }


def test_autogen_runtime_is_registered_only_with_explicit_provider():
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-autogen-v1.json"
    )
    unavailable_registry = (
        autogen_groupchat.build_autogen_agent_adapter_registry()
    )

    assert "autogen-round-robin" not in unavailable_registry.factories
    with pytest.raises(
        AgentRegistryError,
        match="unregistered implementation",
    ):
        unavailable_registry.validate_profile(profile)

    async def fake_provider(_alert):
        return _autogen_decisions(replicas=3)

    available_registry = (
        autogen_groupchat.build_autogen_agent_adapter_registry(
            decision_provider=fake_provider
        )
    )

    adapters = available_registry.create_profile(profile)

    assert "autogen-round-robin" in available_registry.factories
    assert [adapter.name for adapter in adapters] == list(AUTOGEN_AGENT_NAMES)
    assert {adapter.runtime for adapter in adapters} == {
        "autogen-round-robin"
    }


def test_model_client_preflights_autogen_but_fake_provider_stays_offline(
    monkeypatch,
):
    real_import = builtins.__import__

    def import_without_autogen(name, *args, **kwargs):
        if name.startswith("autogen_agentchat"):
            raise ImportError("simulated missing AutoGen dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_autogen)

    with pytest.raises(RuntimeError, match="AutoGen extras are not installed"):
        autogen_groupchat.build_autogen_agent_adapter_registry(
            model_client=object()
        )

    async def fake_provider(_alert):
        return _autogen_decisions(replicas=3)

    registry = autogen_groupchat.build_autogen_agent_adapter_registry(
        decision_provider=fake_provider
    )
    assert "autogen-round-robin" in registry.factories


def test_autogen_profile_normalizes_identity_and_cannot_bypass_validator():
    class FakeProvider:
        def __init__(self):
            self.call_count = 0

        async def __call__(self, _alert):
            self.call_count += 1
            return _autogen_decisions(replicas=99)

    provider = FakeProvider()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-autogen-v1.json"
    )
    coordinator = MutualSupervisionCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(),
        mode=ExecutionMode.MOCK,
        protocol=profile,
        adapter_registry=(
            autogen_groupchat.build_autogen_agent_adapter_registry(
                decision_provider=provider
            )
        ),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert provider.call_count == 1
    assert report["valid"] is False
    assert report["final_status"] == "safe_stopped"
    assert report["human_review_required"] is True
    assert report["safety_validation"]["valid"] is False
    assert "replicas" in report["safety_validation"]["stderr"]
    assert report["executed_actions"] == []
    assert set(report["agent_runtimes"].values()) == {
        "autogen-round-robin"
    }
    assert report["metadata"]["controller"] == "mutual_supervision_autogen"
    assert all(
        decision["run_id"] == report["run_id"]
        and decision["policy_version"] == profile.version
        and decision["agent"] in report["active_agents"]
        for decision in report["initial_decisions"]
    )
    assert all(
        review["run_id"] == report["run_id"]
        and review["policy_version"] == profile.version
        and review["reviewer"] in report["active_agents"]
        for review in report["peer_reviews"]
    )


def test_hybrid_profile_reports_mixed_runtime_controller():
    async def fake_provider(_alert):
        return _autogen_decisions(replicas=99)

    source = load_research_protocol(
        "config/protocol_profiles/four-agent-autogen-v1.json"
    ).to_canonical_dict()
    source.pop("config_hash")
    source["profile_id"] = "four-agent-hybrid-test-v1"
    source["agents"][0]["implementation_id"] = "deterministic-ha"
    source["agents"][0]["runtime"] = "deterministic"
    profile = ResearchProtocolProfile.from_dict(source)
    coordinator = MutualSupervisionCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(),
        mode=ExecutionMode.MOCK,
        protocol=profile,
        adapter_registry=(
            autogen_groupchat.build_autogen_agent_adapter_registry(
                decision_provider=fake_provider
            )
        ),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert set(report["agent_runtimes"].values()) == {
        "deterministic",
        "autogen-round-robin",
    }
    assert report["metadata"]["controller"] == "mutual_supervision_hybrid"


def test_autogen_provider_cache_isolated_between_sequential_runs():
    class SequentialEvidenceProvider:
        def __init__(self):
            self.snapshots = [
                EvidenceSnapshot(
                    namespace="online-boutique",
                    deployment="paymentservice",
                    metric_values={"cpu": 95.0},
                    events=("first-run-event",),
                    log_summary="first-run-log",
                    source="sequential-fake",
                ),
                EvidenceSnapshot(
                    namespace="online-boutique",
                    deployment="paymentservice",
                    metric_values={"cpu": 95.0},
                    events=("second-run-event",),
                    log_summary="second-run-log",
                    source="sequential-fake",
                ),
            ]
            self.call_count = 0

        def collect(self, namespace, deployment):
            snapshot = self.snapshots[self.call_count]
            self.call_count += 1
            assert snapshot.namespace == namespace
            assert snapshot.deployment == deployment
            return snapshot

    class SequentialDecisionProvider:
        def __init__(self):
            self.alerts = []

        async def __call__(self, alert):
            self.alerts.append(alert)
            decisions = _autogen_decisions(replicas=99)
            if len(self.alerts) == 2:
                decisions[-1] = parse_autogen_decision(
                    {
                        "agent": "CostOptimizationAgent",
                        "action": "cost_budget_rejected",
                        "reward": -0.8,
                        "approved": False,
                        "reason": "Second-run evidence exceeds the cost boundary.",
                    },
                    expected_agent="CostOptimizationAgent",
                )
            return decisions

    evidence_provider = SequentialEvidenceProvider()
    decision_provider = SequentialDecisionProvider()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-autogen-v1.json"
    )
    coordinator = MutualSupervisionCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
            min_replicas=1,
            max_replicas=5,
        ),
        evidence_provider=evidence_provider,
        recovery_monitor=FakeRecoveryMonitor(),
        mode=ExecutionMode.MOCK,
        protocol=profile,
        adapter_registry=(
            autogen_groupchat.build_autogen_agent_adapter_registry(
                decision_provider=decision_provider
            )
        ),
    )

    first_report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )
    second_report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert [alert.message for alert in decision_provider.alerts] == [
        "first-run-log",
        "second-run-log",
    ]
    assert first_report["run_id"] != second_report["run_id"]
    assert any(
        review["reviewer"] == "CostOptimizationAgent"
        and review["verdict"] == "approve"
        for review in first_report["peer_reviews"]
    )
    assert any(
        review["reviewer"] == "CostOptimizationAgent"
        and review["verdict"] == "veto"
        for review in second_report["peer_reviews"]
    )
    assert first_report["executed_actions"] == []
    assert second_report["executed_actions"] == []


@pytest.mark.parametrize(
    ("agent", "action", "approved"),
    [
        ("AIServiceHASupportAgent", "ha_no_action", True),
        ("AIApplicationManagementAgent", "app_scale_deployment", False),
        ("AISemiconductorInfraOpsAgent", "infra_capacity_rejected", True),
        ("CostOptimizationAgent", "cost_budget_rejected", True),
    ],
)
def test_contradictory_provider_output_safe_stops_without_approval(
    agent,
    action,
    approved,
):
    async def contradictory_provider(_alert):
        payloads = [
            {
                "agent": decision.agent,
                "action": decision.action,
                "reward": decision.reward,
                "approved": decision.approved,
                "reason": decision.reason,
                "parameters": decision.parameters,
            }
            for decision in _autogen_decisions(replicas=3)
        ]
        contradictory = next(
            payload for payload in payloads if payload["agent"] == agent
        )
        contradictory["action"] = action
        contradictory["approved"] = approved
        return payloads

    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-autogen-v1.json"
    )
    coordinator = MutualSupervisionCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
        ),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(),
        mode=ExecutionMode.MOCK,
        protocol=profile,
        adapter_registry=(
            autogen_groupchat.build_autogen_agent_adapter_registry(
                decision_provider=contradictory_provider
            )
        ),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["valid"] is False
    assert report["final_status"] == "safe_stopped"
    assert report["human_review_required"] is True
    assert report["initial_decisions"] == []
    assert report["peer_reviews"] == []
    assert report["executed_actions"] == []
    assert "contradicts" in " ".join(report["configuration_errors"])


def test_malformed_autogen_runtime_output_fails_without_execution():
    async def malformed_provider(_alert):
        return [
            {
                "agent": "AIServiceHASupportAgent",
                "approved": True,
            }
        ]

    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-autogen-v1.json"
    )
    coordinator = MutualSupervisionCoordinator(
        validator=CommandValidator(
            allowed_namespaces={"online-boutique"},
            allowed_deployments={"paymentservice"},
        ),
        evidence_provider=FakeEvidenceProvider.cpu_saturation(
            namespace="online-boutique",
            deployment="paymentservice",
            value=95.0,
        ),
        recovery_monitor=FakeRecoveryMonitor(),
        mode=ExecutionMode.MOCK,
        protocol=profile,
        adapter_registry=(
            autogen_groupchat.build_autogen_agent_adapter_registry(
                decision_provider=malformed_provider
            )
        ),
    )

    report = coordinator.run(
        namespace="online-boutique",
        deployment="paymentservice",
        metric="cpu",
        threshold=80.0,
    )

    assert report["valid"] is False
    assert report["final_status"] == "safe_stopped"
    assert report["human_review_required"] is True
    assert report["executed_actions"] == []
    assert report["execution_result"]["command"] == ""


def test_autogen_groupchat_coordinator_executes_valid_groupchat_decisions():
    class FakeGroupChat:
        transcript_lines = [
            "AIServiceHASupportAgent: action=ha_scale_out_required approved=True reward=0.90 reason=HA 관점에서 scale-out이 필요합니다.",
            "AIApplicationManagementAgent: action=app_scale_deployment approved=True reward=0.85 reason=paymentservice를 3개 replica로 확장합니다.",
        ]

        async def __call__(self, _alert):
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
        decision_provider=FakeGroupChat(),
        include_transcript=True,
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
    assert result.metadata["transcript"] == "\n".join(FakeGroupChat.transcript_lines)


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


def test_autogen_groupchat_blocks_unsafe_replica_count_before_kubernetes():
    async def fake_groupchat(_alert):
        return [
            parse_autogen_decision(
                {
                    "agent": "AIServiceHASupportAgent",
                    "action": "ha_scale_out_required",
                    "reward": 0.90,
                    "approved": True,
                    "reason": "CPU saturation requires recovery.",
                },
                expected_agent="AIServiceHASupportAgent",
            ),
            parse_autogen_decision(
                {
                    "agent": "AIApplicationManagementAgent",
                    "action": "app_scale_deployment",
                    "reward": 0.85,
                    "approved": True,
                    "reason": "Unsafe over-scaling proposal from LLM path.",
                    "parameters": {
                        "namespace": "online-boutique",
                        "deployment": "paymentservice",
                        "replicas": "99",
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
                    "reason": "Structured response only; validator remains final guard.",
                },
                expected_agent="AISemiconductorInfraOpsAgent",
            ),
            parse_autogen_decision(
                {
                    "agent": "CostOptimizationAgent",
                    "action": "cost_budget_approved",
                    "reward": 0.60,
                    "approved": True,
                    "reason": "Structured response only; validator remains final guard.",
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
        message="Prometheus alert: paymentservice CPU is high",
    )

    try:
        asyncio.run(coordinator.run(alert))
    except CommandValidationError as exc:
        assert "replicas" in str(exc)
    else:
        raise AssertionError("unsafe AutoGen replica count reached execution")


def _autogen_decisions(replicas):
    return [
        parse_autogen_decision(
            {
                "agent": "AIServiceHASupportAgent",
                "action": "ha_scale_out_required",
                "reward": 0.90,
                "approved": True,
                "reason": "HA evidence requires bounded recovery.",
                "parameters": {
                    "namespace": "online-boutique",
                    "deployment": "paymentservice",
                    "replicas": replicas,
                },
            },
            expected_agent="AIServiceHASupportAgent",
        ),
        parse_autogen_decision(
            {
                "agent": "AIApplicationManagementAgent",
                "action": "app_scale_deployment",
                "reward": 0.85,
                "approved": True,
                "reason": "Scale the saturated application deployment.",
                "parameters": {
                    "namespace": "online-boutique",
                    "deployment": "paymentservice",
                    "replicas": replicas,
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
                "reason": "The structured proposal fits infrastructure policy.",
                "parameters": {
                    "namespace": "online-boutique",
                    "deployment": "paymentservice",
                    "replicas": replicas,
                },
            },
            expected_agent="AISemiconductorInfraOpsAgent",
        ),
        parse_autogen_decision(
            {
                "agent": "CostOptimizationAgent",
                "action": "cost_budget_approved",
                "reward": 0.60,
                "approved": True,
                "reason": "The structured proposal fits cost policy.",
                "parameters": {
                    "namespace": "online-boutique",
                    "deployment": "paymentservice",
                    "replicas": replicas,
                },
            },
            expected_agent="CostOptimizationAgent",
        ),
    ]

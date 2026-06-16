import json

import pytest

from aiops_k8s_agents.agent_registry import (
    AgentProfile,
    AgentRegistryError,
    load_agent_registry,
    save_agent_registry,
)


def test_default_agent_registry_loads_four_research_agents():
    registry = load_agent_registry("config/agent_registry.json")

    assert set(registry.agent_names()) == {
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    }
    assert registry.validate_action(
        "AIApplicationManagementAgent",
        "app_scale_deployment",
    )
    assert not registry.validate_action(
        "AIApplicationManagementAgent",
        "kubectl_delete_namespace",
    )


def test_agent_registry_rejects_duplicate_agent_names(tmp_path):
    registry_path = tmp_path / "agents.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": "1",
                "agents": [
                    {
                        "name": "DuplicateAgent",
                        "korean_name": "중복 에이전트",
                        "role": "first",
                        "responsibilities": ["first"],
                        "bounded_actions": ["first_action"],
                        "reward_signals": ["first reward"],
                    },
                    {
                        "name": "DuplicateAgent",
                        "korean_name": "중복 에이전트",
                        "role": "second",
                        "responsibilities": ["second"],
                        "bounded_actions": ["second_action"],
                        "reward_signals": ["second reward"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AgentRegistryError, match="duplicate agent"):
        load_agent_registry(registry_path)


def test_agent_registry_can_register_and_persist_new_agent(tmp_path):
    registry = load_agent_registry("config/agent_registry.json")
    registry.upsert(
        AgentProfile(
            name="AIInferenceOptimizationAgent",
            korean_name="AI 추론 최적화 에이전트",
            role="CPU/GPU VM 기반 추론 배포 최적화",
            responsibilities=("latency SLO를 기준으로 추론 배치 후보를 평가합니다.",),
            bounded_actions=("select_inference_vm",),
            reward_signals=("SLO를 만족하면서 비용을 줄이면 양의 reward",),
        )
    )

    saved_path = tmp_path / "agents.json"
    save_agent_registry(registry, saved_path)
    reloaded = load_agent_registry(saved_path)

    assert reloaded.validate_action(
        "AIInferenceOptimizationAgent",
        "select_inference_vm",
    )

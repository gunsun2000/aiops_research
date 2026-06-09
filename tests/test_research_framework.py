from aiops_k8s_agents.research_framework import (
    AIOPS_PHASES,
    AGENT_RESEARCH_PROFILES,
    agent_action_space,
    infer_aiopslab_api_phase,
    referee_aiopslab_api_call,
    validate_agent_action,
)


def test_research_framework_keeps_four_aiops_phases_from_reference_ppt():
    assert list(AIOPS_PHASES) == [
        "detection",
        "localization",
        "analysis",
        "mitigation",
    ]
    assert AIOPS_PHASES["detection"].korean_name == "장애 탐지"
    assert AIOPS_PHASES["mitigation"].korean_name == "완화 및 복구"


def test_research_framework_defines_bounded_action_space_for_four_agents():
    assert set(AGENT_RESEARCH_PROFILES) == {
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    }
    assert "app_scale_deployment" in agent_action_space(
        "AIApplicationManagementAgent"
    )
    assert validate_agent_action(
        "CostOptimizationAgent",
        "cost_budget_approved",
    )
    assert not validate_agent_action(
        "CostOptimizationAgent",
        "kubectl_delete_namespace",
    )


def test_referee_accepts_only_bounded_aiopslab_api_calls():
    accepted = referee_aiopslab_api_call(
        'get_metrics("test-hotel-reservation", 10)',
        namespace="test-hotel-reservation",
        service="geo",
        metrics_duration_minutes=10,
    )
    rejected = referee_aiopslab_api_call(
        'delete_namespace("kube-system")',
        namespace="test-hotel-reservation",
        service="geo",
        metrics_duration_minutes=10,
    )

    assert accepted.valid is True
    assert accepted.phase == "analysis"
    assert rejected.valid is False


def test_infer_aiopslab_phase_from_api_call():
    assert infer_aiopslab_api_phase('get_logs("ns", "svc")') == "detection"
    assert infer_aiopslab_api_phase('get_metrics("ns", 10)') == "analysis"
    assert infer_aiopslab_api_phase('submit("Yes")') == "detection"

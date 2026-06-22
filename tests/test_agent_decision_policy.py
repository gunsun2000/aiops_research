from aiops_k8s_agents.agent_decision_policy import load_agent_decision_policy
from aiops_k8s_agents.application_agent import AIApplicationManagementAgent
from aiops_k8s_agents.ha_agent import AIServiceHASupportAgent
from aiops_k8s_agents.models import AlertEvent, RecoveryActionKind


def test_ha_agent_adds_policy_evidence_for_threshold_crossing():
    policy = load_agent_decision_policy("config/agent_decision_policy.json")
    agent = AIServiceHASupportAgent(policy=policy)
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu-usage",
        value=82.0,
        threshold=80.0,
        message="CPU slightly above threshold",
    )

    diagnosis, decision = agent.diagnose(alert)

    assert decision.approved is True
    assert diagnosis.cause == "cpu_saturation"
    assert diagnosis.severity == "warning"
    assert diagnosis.evidence["normalized_metric"] == "cpu"
    assert diagnosis.evidence["threshold_exceeded"] is True
    assert diagnosis.evidence["signal_direction"] == "high_is_bad"
    assert 1.0 <= diagnosis.evidence["severity_score"] < 1.10


def test_application_agent_uses_policy_replica_recommendation_by_severity():
    policy = load_agent_decision_policy("config/agent_decision_policy.json")
    ha_agent = AIServiceHASupportAgent(policy=policy)
    app_agent = AIApplicationManagementAgent(policy=policy)
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="cpu",
        value=82.0,
        threshold=80.0,
        message="CPU warning threshold crossed",
    )
    diagnosis, _ = ha_agent.diagnose(alert)

    action, decision = app_agent.propose(alert, diagnosis)

    assert action.kind == RecoveryActionKind.SCALE_OUT
    assert action.replicas == 2
    assert decision.action == "app_scale_deployment"
    assert decision.parameters["replicas"] == "2"
    assert decision.parameters["severity"] == "warning"


def test_application_agent_can_choose_rollout_restart_from_policy():
    policy = load_agent_decision_policy("config/agent_decision_policy.json")
    ha_agent = AIServiceHASupportAgent(policy=policy)
    app_agent = AIApplicationManagementAgent(policy=policy)
    alert = AlertEvent(
        namespace="online-boutique",
        service="paymentservice",
        metric="restart_count",
        value=2.0,
        threshold=1.0,
        message="Pod restart count increased",
    )
    diagnosis, _ = ha_agent.diagnose(alert)

    action, decision = app_agent.propose(alert, diagnosis)

    assert action.kind == RecoveryActionKind.ROLLOUT_RESTART
    assert action.replicas is None
    assert decision.action == "app_rollout_restart"
    assert decision.parameters["action_kind"] == "rollout_restart"

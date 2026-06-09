from aiops_k8s_agents.aiopslab_detection import (
    AIOpsLabDetectionPolicy,
    format_aiopslab_action,
)


def test_detection_policy_first_collects_target_service_logs():
    policy = AIOpsLabDetectionPolicy(
        namespace="test-hotel-reservation",
        service="geo",
    )

    decision = policy.next_action("Please take the next action")

    assert decision.api_call == 'get_logs("test-hotel-reservation", "geo")'
    assert decision.valid is True
    assert decision.metadata["coordinator"] == "AI-MCMP"
    assert decision.metadata["phase"] == "detection"
    assert decision.metadata["phase_model"] == (
        "detection|localization|analysis|mitigation"
    )
    assert decision.metadata["bounded_action"] == (
        'get_logs("test-hotel-reservation", "geo")'
    )
    assert decision.metadata["referee"] == "approved"
    assert decision.metadata["consensus"] == "investigating"
    assert "AIServiceHASupportAgent:ha_collect_logs" in decision.metadata["actions"]


def test_detection_policy_collects_metrics_after_geo_panic_logs():
    policy = AIOpsLabDetectionPolicy(
        namespace="test-hotel-reservation",
        service="geo",
    )
    policy.next_action("Please take the next action")

    decision = policy.next_action("panic: no reachable servers")

    assert decision.api_call == 'get_metrics("test-hotel-reservation", 10)'
    assert decision.valid is True
    assert decision.has_anomaly is True
    assert decision.metadata["phase"] == "analysis"
    assert decision.metadata["consensus"] == "anomaly_detected"
    assert "AIServiceHASupportAgent:ha_anomaly_detected" in decision.metadata["actions"]
    assert "AISemiconductorInfraOpsAgent:infra_dependency_failure_detected" in (
        decision.metadata["actions"]
    )


def test_detection_policy_submits_yes_after_metrics_when_anomaly_was_seen():
    policy = AIOpsLabDetectionPolicy(
        namespace="test-hotel-reservation",
        service="geo",
    )
    policy.next_action("Please take the next action")
    policy.next_action("panic: no reachable servers")

    decision = policy.next_action(
        "Metrics data exported to directory: /tmp/metric_20260608_180631"
    )

    assert decision.api_call == 'submit("Yes")'
    assert decision.valid is True
    assert decision.has_anomaly is True
    assert decision.metadata["phase"] == "detection"
    assert decision.metadata["consensus"] == "approved"
    assert "AIApplicationManagementAgent:app_submit_detection_result" in (
        decision.metadata["actions"]
    )


def test_detection_policy_submits_no_after_clean_logs_and_metrics():
    policy = AIOpsLabDetectionPolicy(
        namespace="test-hotel-reservation",
        service="geo",
    )
    policy.next_action("Please take the next action")
    policy.next_action("geo service started successfully")

    decision = policy.next_action(
        "Metrics data exported to directory: /tmp/metric_20260608_180631"
    )

    assert decision.api_call == 'submit("No")'
    assert decision.valid is True
    assert decision.has_anomaly is False
    assert decision.metadata["consensus"] == "approved"


def test_format_aiopslab_action_wraps_api_call_for_orchestrator_parser():
    assert format_aiopslab_action('submit("Yes")') == 'Action:```\nsubmit("Yes")\n```'

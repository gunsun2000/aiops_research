from aiops_k8s_agents.recovery_evaluator import (
    RECOVERY_AGENT_NAMES,
    RecoveryEvaluatorAgent,
    attach_recovery_evaluation,
)


def recovery_report(
    *,
    final_status="recovered",
    recovery_success=True,
    replans=0,
    safety_valid=True,
    execution_valid=True,
    evidence=True,
):
    report = {
        "final_status": final_status,
        "evidence": {
            "scenario": "cpu-stress",
            "namespace": "online-boutique",
            "deployment": "paymentservice",
            "metric_values": {"cpu": 95.0},
            "source": "prometheus+kubernetes",
        }
        if evidence
        else {},
        "diagnosis": {"cause": "cpu_saturation"} if evidence else {},
        "selected_action": {"kind": "scale_out"},
        "executed_actions": [{"kind": "scale_out"}],
        "replanning_attempts": [{} for _ in range(replans)],
        "safety_validation": {"valid": safety_valid},
        "execution_result": {"valid": execution_valid},
        "recovery_monitoring": {
            "recovery_success": recovery_success,
            "recovery_seconds": 12.0,
        },
    }
    return report


def test_successful_recovery_gets_positive_bounded_team_and_agent_rewards():
    evaluation = RecoveryEvaluatorAgent().evaluate(recovery_report()).to_dict()

    assert evaluation["team_reward"] > 0
    assert set(evaluation["agent_rewards"]) == set(RECOVERY_AGENT_NAMES)
    assert -1.0 <= evaluation["team_reward"] <= 1.0
    assert all(-1.0 <= value <= 1.0 for value in evaluation["agent_rewards"].values())
    assert set(evaluation["components"]) >= {
        "outcome",
        "efficiency",
        "safety",
        "evidence_quality",
    }


def test_failed_and_safe_stopped_reports_are_not_positive():
    evaluator = RecoveryEvaluatorAgent()

    failed = evaluator.evaluate(
        recovery_report(final_status="failed", recovery_success=False)
    ).to_dict()
    stopped = evaluator.evaluate(
        recovery_report(final_status="safe_stopped", recovery_success=False)
    ).to_dict()

    assert failed["team_reward"] <= 0
    assert stopped["team_reward"] <= 0


def test_replanning_reduces_efficiency():
    evaluator = RecoveryEvaluatorAgent()
    direct = evaluator.evaluate(recovery_report(replans=0)).to_dict()
    replanned = evaluator.evaluate(recovery_report(replans=2)).to_dict()

    assert replanned["components"]["efficiency"] < direct["components"]["efficiency"]
    assert replanned["team_reward"] < direct["team_reward"]


def test_efficiency_uses_explicit_protocol_recovery_budget_only():
    report = recovery_report()
    report["recovery_monitoring"]["recovery_seconds"] = 5.0
    report["protocol_config"] = {"recovery_budget_seconds": 10.0}

    evaluation = RecoveryEvaluatorAgent().evaluate(report).to_dict()

    assert evaluation["components"]["efficiency"] < 1.0

    no_budget = recovery_report()
    no_budget["recovery_monitoring"]["recovery_seconds"] = 5.0
    without_budget = RecoveryEvaluatorAgent().evaluate(no_budget).to_dict()
    assert without_budget["components"]["efficiency"] == 1.0


def test_unsafe_execution_reduces_safety():
    evaluator = RecoveryEvaluatorAgent()
    safe = evaluator.evaluate(recovery_report()).to_dict()
    unsafe = evaluator.evaluate(
        recovery_report(safety_valid=False, execution_valid=False)
    ).to_dict()

    assert unsafe["components"]["safety"] < safe["components"]["safety"]
    assert unsafe["team_reward"] < safe["team_reward"]


def test_missing_evidence_is_not_fabricated_as_high_quality():
    evaluation = RecoveryEvaluatorAgent().evaluate(
        recovery_report(evidence=False)
    ).to_dict()

    assert evaluation["components"]["evidence_quality"] < 1.0
    assert evaluation["components"]["evidence_quality"] >= 0.0


def test_attach_evaluation_persists_authoritative_fields():
    report = recovery_report()
    attach_recovery_evaluation(report)

    assert report["evaluation"]["evaluator"] == "RecoveryEvaluatorAgent"
    assert "team_reward" in report["evaluation"]
    assert set(report["evaluation"]["agent_rewards"]) == set(RECOVERY_AGENT_NAMES)
    assert "agent_contributions" not in report["evaluation"]


def test_legacy_agent_contribution_rewards_are_not_the_team_reward():
    report = recovery_report()
    report["agent_contributions"] = {
        agent: {"reward": 1.0} for agent in RECOVERY_AGENT_NAMES
    }

    evaluation = RecoveryEvaluatorAgent().evaluate(report).to_dict()

    assert evaluation["team_reward"] <= 1.0
    assert evaluation["team_reward"] != 4.0

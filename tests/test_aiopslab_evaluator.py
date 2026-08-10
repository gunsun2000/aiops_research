from aiops_k8s_agents.aiopslab_evaluator import (
    AIOPSLAB_AGENT_NAMES,
    AIOpsLabEvaluatorAgent,
    attach_aiopslab_evaluation,
)


def _results(accuracy="Correct", *, ttd=12.0, steps=3):
    return {
        "final_state": "SubmissionStatus.VALID_SUBMISSION",
        "results": {
            "Detection Accuracy": accuracy,
            "TTD": ttd,
            "steps": steps,
        },
    }


def _decisions(*, safe=True, include_logs=True, include_metrics=True):
    calls = []
    if include_logs:
        calls.append('get_logs("test-hotel-reservation", "geo")')
    if include_metrics:
        calls.append('get_metrics("test-hotel-reservation", 10)')
    calls.append('submit("Yes")')
    return [
        {
            "step": index,
            "api_call": call,
            "valid": safe,
            "metadata": {"referee": "approved" if safe else "rejected"},
        }
        for index, call in enumerate(calls, start=1)
    ]


def test_evaluator_returns_team_and_per_agent_rewards_from_run_evidence():
    evaluator = AIOpsLabEvaluatorAgent(max_steps=8, metrics_duration_minutes=10)

    evaluation = evaluator.evaluate(_results(), _decisions())

    assert evaluation.evaluator == "AIOpsLabEvaluatorAgent"
    assert evaluation.rubric_version == "evaluator-v1"
    assert set(evaluation.agent_rewards) == set(AIOPSLAB_AGENT_NAMES)
    assert evaluation.components["correctness"] == 1.0
    assert evaluation.components["safety"] == 1.0
    assert evaluation.components["evidence_quality"] == 1.0
    assert evaluation.team_reward > 0.0
    assert "Correct" in evaluation.reason


def test_incorrect_detection_cannot_receive_positive_team_reward():
    evaluator = AIOpsLabEvaluatorAgent(max_steps=8, metrics_duration_minutes=10)

    evaluation = evaluator.evaluate(
        _results("Incorrect", ttd=1.0, steps=1),
        _decisions(),
    )

    assert evaluation.components["correctness"] == -1.0
    assert evaluation.team_reward <= 0.0


def test_faster_fewer_step_correct_run_scores_higher():
    evaluator = AIOpsLabEvaluatorAgent(max_steps=8, metrics_duration_minutes=10)

    efficient = evaluator.evaluate(
        _results("Correct", ttd=2.0, steps=2),
        _decisions(),
    )
    inefficient = evaluator.evaluate(
        _results("Correct", ttd=500.0, steps=8),
        _decisions(),
    )

    assert efficient.components["efficiency"] > inefficient.components["efficiency"]
    assert efficient.team_reward > inefficient.team_reward
    assert efficient.agent_rewards["CostOptimizationAgent"] > (
        inefficient.agent_rewards["CostOptimizationAgent"]
    )


def test_safety_failure_reduces_team_and_infra_reward():
    evaluator = AIOpsLabEvaluatorAgent(max_steps=8, metrics_duration_minutes=10)

    safe = evaluator.evaluate(_results(), _decisions(safe=True))
    unsafe = evaluator.evaluate(_results(), _decisions(safe=False))

    assert safe.components["safety"] == 1.0
    assert unsafe.components["safety"] == -1.0
    assert unsafe.team_reward < safe.team_reward
    assert unsafe.agent_rewards["AISemiconductorInfraOpsAgent"] < (
        safe.agent_rewards["AISemiconductorInfraOpsAgent"]
    )


def test_missing_evidence_is_not_fabricated_and_all_rewards_are_bounded():
    evaluator = AIOpsLabEvaluatorAgent(max_steps=8, metrics_duration_minutes=10)

    evaluation = evaluator.evaluate(
        _results("Correct", ttd=None, steps=None),
        _decisions(include_logs=False, include_metrics=False),
    )

    assert evaluation.components["ttd_efficiency"] is None
    assert evaluation.components["step_efficiency"] is None
    assert evaluation.components["efficiency"] == 0.0
    assert evaluation.components["evidence_quality"] == 0.0
    assert -1.0 <= evaluation.team_reward <= 1.0
    assert all(-1.0 <= value <= 1.0 for value in evaluation.agent_rewards.values())


def test_application_reward_reflects_evidence_quality():
    evaluator = AIOpsLabEvaluatorAgent(max_steps=8, metrics_duration_minutes=10)

    complete = evaluator.evaluate(
        _results(),
        _decisions(include_logs=True, include_metrics=True),
    )
    incomplete = evaluator.evaluate(
        _results(),
        _decisions(include_logs=True, include_metrics=False),
    )

    assert complete.agent_rewards["AIApplicationManagementAgent"] > (
        incomplete.agent_rewards["AIApplicationManagementAgent"]
    )


def test_attach_evaluation_persists_objective_team_and_agent_rewards():
    report = {
        "problem_id": "misconfig_app_hotel_res-detection-1",
        "decisions": _decisions(),
        "aiopslab_results": _results("Correct", ttd=4.0, steps=3),
    }

    updated = attach_aiopslab_evaluation(
        report,
        max_steps=8,
        metrics_duration_minutes=10,
    )

    assert updated is report
    assert updated["evaluation"]["evaluator"] == "AIOpsLabEvaluatorAgent"
    assert updated["evaluation"]["team_reward"] > 0.0
    assert set(updated["evaluation"]["agent_rewards"]) == set(AIOPSLAB_AGENT_NAMES)
    assert "reward_total" not in updated["decisions"][-1]["metadata"]

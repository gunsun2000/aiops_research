import json

from aiops_k8s_agents.aiopslab_results import (
    summarize_aiopslab_reports,
    write_aiopslab_summary_files,
)


AGENT_REWARDS_1 = {
    "AIServiceHASupportAgent": 0.92,
    "AIApplicationManagementAgent": 0.88,
    "AISemiconductorInfraOpsAgent": 0.90,
    "CostOptimizationAgent": 0.81,
}
AGENT_REWARDS_2 = {
    "AIServiceHASupportAgent": 0.82,
    "AIApplicationManagementAgent": 0.78,
    "AISemiconductorInfraOpsAgent": 0.80,
    "CostOptimizationAgent": 0.71,
}


def _write_report(
    path,
    *,
    ttd,
    steps,
    team_reward,
    agent_rewards=AGENT_REWARDS_1,
    metric_success=True,
    include_evaluation=True,
):
    metric_text = (
        "Metrics data exported to directory: /tmp/metric_20260608_185426"
        if metric_success
        else "HTTPConnectionPool(host='localhost', port=32000): connection refused"
    )
    report = {
        "problem_id": "misconfig_app_hotel_res-detection-1",
        "namespace": "test-hotel-reservation",
        "service": "geo",
        "started_at": "2026-06-08T18:52:25",
        "finished_at": "2026-06-08T18:55:07",
        "decisions": [
            {
                "step": 1,
                "api_call": 'get_logs("test-hotel-reservation", "geo")',
                "metadata": {"phase": "detection"},
                "observation_excerpt": "Please take the next action",
            },
            {
                "step": 2,
                "api_call": 'get_metrics("test-hotel-reservation", 10)',
                "metadata": {"phase": "analysis"},
                "observation_excerpt": "panic: no reachable servers",
            },
            {
                "step": 3,
                "api_call": 'submit("Yes")',
                "metadata": {"phase": "detection"},
                "observation_excerpt": metric_text,
            },
        ],
        "aiopslab_results": {
            "final_state": "SubmissionStatus.VALID_SUBMISSION",
            "results": {
                "Detection Accuracy": "Correct",
                "TTD": ttd,
                "steps": steps,
            },
            "framework_overhead": 157.45,
        },
    }
    if include_evaluation:
        report["evaluation"] = {
            "evaluator": "AIOpsLabEvaluatorAgent",
            "rubric_version": "evaluator-v1",
            "team_reward": team_reward,
            "agent_rewards": agent_rewards,
            "components": {
                "correctness": 1.0,
                "efficiency": 0.8,
                "safety": 1.0,
                "evidence_quality": 1.0,
            },
            "reason": "objective evidence",
        }
    path.write_text(json.dumps(report), encoding="utf-8")


def test_summarize_aiopslab_reports_extracts_evaluator_rewards(tmp_path):
    _write_report(
        tmp_path / "20260608-1_aiopslab_auto_detection.json",
        ttd=3.6,
        steps=3,
        team_reward=0.90,
        agent_rewards=AGENT_REWARDS_1,
    )
    _write_report(
        tmp_path / "20260608-2_aiopslab_auto_detection.json",
        ttd=4.4,
        steps=3,
        team_reward=0.80,
        agent_rewards=AGENT_REWARDS_2,
    )

    summary = summarize_aiopslab_reports(tmp_path)

    assert summary.total_runs == 2
    assert summary.correct_runs == 2
    assert summary.average_ttd == 4.0
    assert summary.average_steps == 3.0
    assert summary.average_final_reward == 0.85
    assert summary.average_team_reward == 0.85
    assert summary.average_agent_rewards["AIServiceHASupportAgent"] == 0.87
    assert summary.average_agent_rewards["CostOptimizationAgent"] == 0.76
    assert summary.records[0].team_reward == 0.90
    assert summary.records[0].agent_rewards == AGENT_REWARDS_1
    assert summary.records[0].phase_coverage == "detection+analysis"
    assert summary.records[0].metric_exported is True
    assert summary.records[0].metric_path == "/tmp/metric_20260608_185426"


def test_summarize_aiopslab_reports_ignores_legacy_decision_reward_total(tmp_path):
    path = tmp_path / "20260608-legacy_aiopslab_auto_detection.json"
    _write_report(
        path,
        ttd=3.6,
        steps=3,
        team_reward=0.90,
        include_evaluation=False,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["decisions"][-1]["metadata"]["reward_total"] = "3.10"
    path.write_text(json.dumps(data), encoding="utf-8")

    summary = summarize_aiopslab_reports(tmp_path)

    assert summary.records[0].final_reward is None
    assert summary.records[0].team_reward is None
    assert summary.average_final_reward is None
    assert summary.average_team_reward is None


def test_summarize_aiopslab_reports_marks_metric_failures(tmp_path):
    _write_report(
        tmp_path / "20260608-1_aiopslab_auto_detection.json",
        ttd=3.6,
        steps=3,
        team_reward=0.90,
        metric_success=False,
    )

    summary = summarize_aiopslab_reports(tmp_path)

    assert summary.total_runs == 1
    assert summary.metric_success_runs == 0
    assert summary.records[0].metric_exported is False
    assert summary.records[0].metric_path == ""


def test_write_aiopslab_summary_files_outputs_team_and_agent_rewards(tmp_path):
    _write_report(
        tmp_path / "20260608-1_aiopslab_auto_detection.json",
        ttd=3.6,
        steps=3,
        team_reward=0.90,
    )
    summary = summarize_aiopslab_reports(tmp_path)

    markdown_path = tmp_path / "summary.md"
    csv_path = tmp_path / "summary.csv"
    write_aiopslab_summary_files(
        summary,
        markdown_path=markdown_path,
        csv_path=csv_path,
    )

    markdown = markdown_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8")

    assert "average_team_reward: 0.900" in markdown
    assert "HA reward" in markdown
    assert "0.90" in markdown
    assert "team_reward" in csv_text
    assert "ha_reward" in csv_text
    assert "cost_reward" in csv_text

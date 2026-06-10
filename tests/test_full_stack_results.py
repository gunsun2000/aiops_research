import json

from aiops_k8s_agents.full_stack_results import (
    summarize_full_stack_reports,
    write_full_stack_summary_files,
)


def _write_feedback_report(
    path,
    *,
    mode="real",
    passed=2,
    failed=0,
    autogen=False,
    initial_replicas=1,
    final_replicas=3,
    reward="3.05",
):
    path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for iteration in range(1, passed + failed + 1):
        valid = iteration <= passed
        records.append(
            {
                "iteration": iteration,
                "before": {
                    "deployment_status": {
                        "desired_replicas": initial_replicas,
                    }
                },
                "result": {
                    "command": (
                        "kubectl scale deployment paymentservice "
                        "--replicas=3 -n online-boutique"
                        if valid
                        else ""
                    ),
                    "mode": mode,
                    "valid": valid,
                    "metadata": {"reward_total": reward} if valid else {},
                },
                "after": {
                    "deployment_status": {
                        "desired_replicas": final_replicas,
                    }
                },
            }
        )
    path.write_text(
        json.dumps(
            {
                "command": "feedback-loop",
                "mode": mode,
                "iterations": passed + failed,
                "passed": passed,
                "failed": failed,
                "autogen": autogen,
                "records": records,
            }
        ),
        encoding="utf-8",
    )


def test_summarize_full_stack_reports_extracts_real_control_evidence(tmp_path):
    _write_feedback_report(
        tmp_path / "pod-kill" / "run_feedback_loop_real.json"
    )
    _write_feedback_report(
        tmp_path / "cpu-stress" / "run_feedback_loop_real.json",
        autogen=True,
        reward="2.95",
    )

    summary = summarize_full_stack_reports(tmp_path)

    assert summary.total_scenarios == 2
    assert summary.successful_scenarios == 2
    assert summary.total_iterations == 4
    assert summary.total_passed == 4
    assert summary.total_failed == 0
    assert summary.average_reward == 3.0
    assert summary.records[0].scenario == "cpu-stress"
    assert summary.records[0].controller == "autogen"
    assert summary.records[0].real_scale_verified is True
    assert summary.records[0].initial_replicas == 1
    assert summary.records[0].final_replicas == 3


def test_summarize_full_stack_reports_does_not_mark_dry_run_as_real_control(tmp_path):
    _write_feedback_report(
        tmp_path / "network-delay" / "run_feedback_loop_dry_run.json",
        mode="dry-run",
        final_replicas=1,
    )

    summary = summarize_full_stack_reports(tmp_path)

    assert summary.records[0].success_rate == 1.0
    assert summary.records[0].real_scale_verified is False


def test_write_full_stack_summary_files_outputs_markdown_and_csv(tmp_path):
    _write_feedback_report(
        tmp_path / "memory-stress" / "run_feedback_loop_real.json"
    )
    summary = summarize_full_stack_reports(tmp_path)
    markdown_path = tmp_path / "final_summary.md"
    csv_path = tmp_path / "final_summary.csv"

    write_full_stack_summary_files(summary, markdown_path, csv_path)

    markdown = markdown_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "# Full-stack 4-Agent Final Experiment Summary" in markdown
    assert "| memory-stress | real | deterministic | 2/2 | 100.0%" in markdown
    assert "scenario,mode,controller,iterations,passed,failed" in csv_text
    assert "memory-stress,real,deterministic,2,2,0" in csv_text

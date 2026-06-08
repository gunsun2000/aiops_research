import json

from aiops_k8s_agents.aiopslab_results import (
    summarize_aiopslab_reports,
    write_aiopslab_summary_files,
)


def _write_report(path, *, ttd, steps, reward_total, metric_success=True):
    metric_text = (
        "Metrics data exported to directory: /tmp/metric_20260608_185426"
        if metric_success
        else "HTTPConnectionPool(host='localhost', port=32000): connection refused"
    )
    path.write_text(
        json.dumps(
            {
                "problem_id": "misconfig_app_hotel_res-detection-1",
                "namespace": "test-hotel-reservation",
                "service": "geo",
                "started_at": "2026-06-08T18:52:25",
                "finished_at": "2026-06-08T18:55:07",
                "decisions": [
                    {
                        "step": 1,
                        "api_call": 'get_logs("test-hotel-reservation", "geo")',
                        "metadata": {"reward_total": "1.55"},
                        "observation_excerpt": "Please take the next action",
                    },
                    {
                        "step": 2,
                        "api_call": 'get_metrics("test-hotel-reservation", 10)',
                        "metadata": {"reward_total": "3.10"},
                        "observation_excerpt": "panic: no reachable servers",
                    },
                    {
                        "step": 3,
                        "api_call": 'submit("Yes")',
                        "metadata": {"reward_total": reward_total},
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
        ),
        encoding="utf-8",
    )


def test_summarize_aiopslab_reports_extracts_research_metrics(tmp_path):
    _write_report(tmp_path / "20260608-1_aiopslab_auto_detection.json", ttd=3.6, steps=3, reward_total="3.10")
    _write_report(tmp_path / "20260608-2_aiopslab_auto_detection.json", ttd=4.4, steps=3, reward_total="3.00")

    summary = summarize_aiopslab_reports(tmp_path)

    assert summary.total_runs == 2
    assert summary.correct_runs == 2
    assert summary.average_ttd == 4.0
    assert summary.average_steps == 3.0
    assert summary.average_final_reward == 3.05
    assert summary.records[0].metric_exported is True
    assert summary.records[0].metric_path == "/tmp/metric_20260608_185426"


def test_summarize_aiopslab_reports_marks_metric_failures(tmp_path):
    _write_report(
        tmp_path / "20260608-1_aiopslab_auto_detection.json",
        ttd=3.6,
        steps=3,
        reward_total="3.10",
        metric_success=False,
    )

    summary = summarize_aiopslab_reports(tmp_path)

    assert summary.total_runs == 1
    assert summary.metric_success_runs == 0
    assert summary.records[0].metric_exported is False
    assert summary.records[0].metric_path == ""


def test_write_aiopslab_summary_files_outputs_markdown_and_csv(tmp_path):
    _write_report(tmp_path / "20260608-1_aiopslab_auto_detection.json", ttd=3.6, steps=3, reward_total="3.10")
    summary = summarize_aiopslab_reports(tmp_path)

    markdown_path = tmp_path / "summary.md"
    csv_path = tmp_path / "summary.csv"
    write_aiopslab_summary_files(summary, markdown_path=markdown_path, csv_path=csv_path)

    markdown = markdown_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8")

    assert "AIOpsLab 4-Agent Detection 반복 실험 요약" in markdown
    assert "| 1 | Correct | 3.600 | 3 | 3.10 | yes |" in markdown
    assert "run_index,file,detection_accuracy,ttd,steps,final_reward,metric_exported,metric_path" in csv_text

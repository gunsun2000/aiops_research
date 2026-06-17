import csv
import json
from pathlib import Path

from aiops_k8s_agents.recovery_statistics import (
    summarize_recovery_statistics,
    write_recovery_statistics,
)


def _write_outcomes(path: Path) -> None:
    records = [
        {
            "scenario": "cpu-stress",
            "action": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "kind": "scale_out",
                "replicas": 3,
                "reason": "test",
            },
            "recovery_success": True,
            "availability_recovery": 1.0,
            "metric_improvement": 0.9,
            "recovery_seconds": 12.0,
            "replica_delta": 2,
            "command_count": 1,
            "safety_valid": True,
            "measurement_valid": True,
        },
        {
            "scenario": "cpu-stress",
            "action": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "kind": "scale_out",
                "replicas": 3,
                "reason": "test",
            },
            "recovery_success": False,
            "availability_recovery": 0.5,
            "metric_improvement": 0.4,
            "recovery_seconds": 30.0,
            "replica_delta": 2,
            "command_count": 1,
            "safety_valid": True,
            "measurement_valid": True,
        },
        {
            "scenario": "cpu-stress",
            "action": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "kind": "observe_only",
                "replicas": None,
                "reason": "test",
            },
            "recovery_success": True,
            "availability_recovery": 1.0,
            "metric_improvement": 0.7,
            "recovery_seconds": 50.0,
            "replica_delta": 0,
            "command_count": 0,
            "safety_valid": True,
            "measurement_valid": True,
        },
        {
            "scenario": "network-delay",
            "action": {
                "namespace": "online-boutique",
                "deployment": "paymentservice",
                "kind": "rollout_restart",
                "replicas": None,
                "reason": "test",
            },
            "recovery_success": True,
            "availability_recovery": 1.0,
            "metric_improvement": 0.8,
            "recovery_seconds": 18.0,
            "replica_delta": 0,
            "command_count": 1,
            "safety_valid": True,
            "measurement_valid": True,
        },
    ]
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def test_summarize_recovery_statistics_computes_mean_and_success_rate(tmp_path):
    input_path = tmp_path / "outcomes.jsonl"
    _write_outcomes(input_path)

    report = summarize_recovery_statistics(input_path)

    assert report["valid"] is True
    assert report["input_records"] == 4
    assert report["valid_measurements"] == 4
    cpu_scale = next(
        row
        for row in report["scenario_action_statistics"]
        if row["scenario"] == "cpu-stress" and row["action"] == "scale_out"
    )
    assert cpu_scale["runs"] == 2
    assert cpu_scale["success_rate"] == 0.5
    assert cpu_scale["mean_recovery_seconds"] == 21.0
    assert cpu_scale["mean_metric_improvement"] == 0.65
    assert report["overall"]["success_rate"] == 0.75


def test_write_recovery_statistics_outputs_tables_and_svg_graphs(tmp_path):
    input_path = tmp_path / "outcomes.jsonl"
    output_dir = tmp_path / "statistics"
    _write_outcomes(input_path)

    report = summarize_recovery_statistics(input_path)
    write_recovery_statistics(report, output_dir)

    expected_files = {
        "quantitative_summary.json",
        "scenario_action_statistics.csv",
        "policy_reward_statistics.csv",
        "quantitative_summary.md",
        "mean_recovery_seconds_by_action.svg",
        "success_rate_by_action.svg",
        "reward_by_policy.svg",
    }
    assert expected_files.issubset({path.name for path in output_dir.iterdir()})

    rows = list(
        csv.DictReader(
            (output_dir / "scenario_action_statistics.csv").open(
                encoding="utf-8",
                newline="",
            )
        )
    )
    assert {"scenario", "action", "success_rate", "mean_recovery_seconds"}.issubset(
        rows[0]
    )

    markdown = (output_dir / "quantitative_summary.md").read_text(encoding="utf-8")
    assert "Recovery Quantitative Statistics" in markdown
    assert "cpu-stress" in markdown

    svg = (output_dir / "reward_by_policy.svg").read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "balanced" in svg

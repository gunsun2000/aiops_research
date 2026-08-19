import json
from pathlib import Path

from aiops_k8s_agents.cli import main


EXAMPLE = "config/examples/model_partition_job.json"
POLICY = "config/model_partition_policy.json"


def test_plan_model_partition_cli_writes_validated_artifact(tmp_path, capsys):
    exit_code = main(
        [
            "plan-model-partition",
            "--input",
            EXAMPLE,
            "--policy",
            POLICY,
            "--artifact-root",
            str(tmp_path),
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["status"] == "planned"
    assert report["plan"]["selected_candidate"]["split_points"] == [3]
    assert report["validation"]["valid"] is True
    assert Path(report["artifact_path"]).is_file()


def test_plan_model_partition_cli_rejects_unapproved_mode(tmp_path, capsys):
    payload = json.loads(Path(EXAMPLE).read_text(encoding="utf-8"))
    payload["execution_mode"]["approved"] = False
    input_path = tmp_path / "unapproved.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(
        [
            "plan-model-partition",
            "--input",
            str(input_path),
            "--policy",
            POLICY,
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert report["valid"] is False
    assert report["error"]["code"] == "approved_mode_required"


def test_replan_model_partition_cli_selects_a_different_split(tmp_path, capsys):
    assert main(
        [
            "plan-model-partition",
            "--input",
            EXAMPLE,
            "--policy",
            POLICY,
            "--artifact-root",
            str(tmp_path / "initial"),
        ]
    ) == 0
    initial = json.loads(capsys.readouterr().out)
    previous_path = tmp_path / "previous.json"
    previous_path.write_text(
        json.dumps(initial["plan"]),
        encoding="utf-8",
    )
    failure = {
        "signal": "latency_slo_violation",
        "details": "observed latency exceeded the SLO",
    }
    failure_path = tmp_path / "failure.json"
    failure_path.write_text(json.dumps(failure), encoding="utf-8")

    exit_code = main(
        [
            "replan-model-partition",
            "--input",
            EXAMPLE,
            "--previous-plan",
            str(previous_path),
            "--failure",
            str(failure_path),
            "--policy",
            POLICY,
            "--artifact-root",
            str(tmp_path / "replan"),
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["replanning"]["attempt"] == 1
    assert report["plan"]["selected_candidate"]["split_points"] != [3]

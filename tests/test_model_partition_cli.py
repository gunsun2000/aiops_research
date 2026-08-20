import json
from pathlib import Path

from aiops_k8s_agents.cli import main


EXAMPLE = "config/examples/model_partition_job.json"
V2_EXAMPLE = "config/examples/model_partition_inference_v2.json"
POLICY = "config/model_partition_policy.json"


def _v2_input_path(tmp_path: Path) -> Path:
    payload = json.loads(Path(V2_EXAMPLE).read_text(encoding="utf-8"))
    payload["coordination_plan"]["payload"]["latency_slo_ms"] = 500.0
    payload["coordination_plan"]["payload"]["constraints"][
        "max_end_to_end_latency_ms"
    ] = 500.0
    path = tmp_path / "inference-v2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _custom_policy_path(tmp_path: Path) -> Path:
    policy = json.loads(Path(POLICY).read_text(encoding="utf-8"))
    policy["version"] = "partition-policy-cli-test"
    policy["confidence"]["base"] = 0.61
    policy["strategy_policies"]["inference-partition-v1"]["objectives"] = {
        "latency": 0.1,
        "memory_pressure": 0.7,
        "communication": 0.2,
    }
    path = tmp_path / "custom-policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


def _latency_feedback(report: dict) -> dict:
    return {
        "signal": "latency_slo_violation",
        "source": "runtime-monitor",
        "reason": "observed latency exceeded the approved SLO",
        "received_at": "2026-08-20T00:00:00+00:00",
        "plan_id": report["plan"]["plan_id"],
        "plan_version": report["plan"]["plan_version"],
    }


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


def test_plan_model_partition_v2_cli_emits_versioned_plan(tmp_path, capsys):
    input_path = _v2_input_path(tmp_path)

    exit_code = main(
        [
            "plan-model-partition-v2",
            "--input",
            str(input_path),
            "--policy",
            POLICY,
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["plan"]["plan_version"] == 1
    assert report["scheduling_handoff"]["status"] == "ready"
    assert report["scheduling_handoff"]["scheduler_ref"] is None


def test_feedback_model_partition_cli_emits_child_plan(tmp_path, capsys):
    artifact_root = tmp_path / "artifacts"
    input_path = _v2_input_path(tmp_path)
    assert main(
        [
            "plan-model-partition-v2",
            "--input",
            str(input_path),
            "--policy",
            POLICY,
            "--artifact-root",
            str(artifact_root),
        ]
    ) == 0
    initial = json.loads(capsys.readouterr().out)
    feedback_path = tmp_path / "feedback.json"
    feedback_path.write_text(
        json.dumps(
            {
                "signal": "latency_slo_violation",
                "source": "runtime-monitor",
                "reason": "observed latency exceeded the approved SLO",
                "received_at": "2026-08-20T00:00:00+00:00",
                "plan_id": initial["plan"]["plan_id"],
                "plan_version": initial["plan"]["plan_version"],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "feedback-model-partition",
            "--plan-id",
            initial["plan"]["plan_id"],
            "--feedback",
            str(feedback_path),
            "--policy",
            POLICY,
            "--artifact-root",
            str(artifact_root),
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["plan"]["parent_plan_id"] == initial["plan"]["plan_id"]
    assert report["plan"]["plan_version"] == 2


def test_plan_model_partition_v2_cli_emits_safe_failure_without_error_exit(
    tmp_path, capsys
):
    exit_code = main(
        [
            "plan-model-partition-v2",
            "--input",
            V2_EXAMPLE,
            "--policy",
            POLICY,
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ]
    )

    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["status"] == "blocked"
    assert report["plan"]["human_review_required"] is True
    assert report["scheduling_handoff"] == {
        **report["scheduling_handoff"],
        "status": "blocked",
        "scheduler_ref": None,
    }


def test_plan_model_partition_v2_cli_reports_invalid_input(tmp_path, capsys):
    input_path = tmp_path / "invalid.json"
    input_path.write_text("{", encoding="utf-8")

    exit_code = main(
        [
            "plan-model-partition-v2",
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
    assert report["error"]["code"] == "invalid_input"


def test_v2_cli_threads_custom_policy_to_plan_artifact_and_feedback(tmp_path, capsys):
    artifact_root = tmp_path / "artifacts"
    input_path = _v2_input_path(tmp_path)
    policy_path = _custom_policy_path(tmp_path)

    assert main(
        [
            "plan-model-partition-v2",
            "--input",
            str(input_path),
            "--policy",
            str(policy_path),
            "--artifact-root",
            str(artifact_root),
        ]
    ) == 0
    initial = json.loads(capsys.readouterr().out)
    feedback_path = tmp_path / "feedback.json"
    feedback_path.write_text(json.dumps(_latency_feedback(initial)), encoding="utf-8")

    assert main(
        [
            "feedback-model-partition",
            "--plan-id",
            initial["plan"]["plan_id"],
            "--feedback",
            str(feedback_path),
            "--policy",
            str(policy_path),
            "--artifact-root",
            str(artifact_root),
        ]
    ) == 0
    feedback = json.loads(capsys.readouterr().out)

    assert initial["plan"]["strategy_version"] == (
        "inference-partition-v1:partition-policy-cli-test"
    )
    assert initial["evaluation"]["policy_version"] == "partition-policy-cli-test"
    assert feedback["evaluation"]["policy_version"] == "partition-policy-cli-test"
    assert feedback["plan"]["strategy_version"] == initial["plan"]["strategy_version"]

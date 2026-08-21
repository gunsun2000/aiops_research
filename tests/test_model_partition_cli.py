import json
from pathlib import Path

from aiops_k8s_agents.cli import main
from aiops_k8s_agents.partition_features import FEATURE_ORDER
from aiops_k8s_agents.partition_ranker_repository import (
    VALIDATION_METRIC_KEYS,
    PartitionRankerModelArtifact,
    PartitionRankerRepository,
)
from aiops_k8s_agents.partition_service import run_partition_planning


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


def _infeasible_v2_input_path(tmp_path: Path) -> Path:
    payload = json.loads(Path(V2_EXAMPLE).read_text(encoding="utf-8"))
    payload["coordination_plan"]["payload"]["latency_slo_ms"] = 1.0
    payload["coordination_plan"]["payload"]["constraints"][
        "max_end_to_end_latency_ms"
    ] = 1.0
    path = tmp_path / "inference-v2-infeasible.json"
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


def _ranker_registry(root: Path) -> Path:
    registry = root / "ranker-registry"
    artifact = PartitionRankerModelArtifact(
        schema_version="partition-ranker-model-v2",
        model_type="ridge_reward_regressor",
        model_version="partition-ridge-observed-v1",
        feature_schema_version="partition-feature-v1",
        trained_at="2026-08-21T00:00:00Z",
        training_dataset_hash="a" * 64,
        training_scope="observed",
        sample_count=30,
        group_count=5,
        feature_order=FEATURE_ORDER,
        feature_mean=tuple(0.0 for _ in FEATURE_ORDER),
        feature_scale=tuple(1.0 for _ in FEATURE_ORDER),
        coefficients=tuple(0.0 for _ in FEATURE_ORDER),
        intercept=0.0,
        training_feature_ranges={name: (0.0, 10_000_000_000.0) for name in FEATURE_ORDER},
        validation_metrics={
            **{key: 0.0 for key in VALIDATION_METRIC_KEYS},
            "holdout_mae": 0.1,
            "mae": 0.1,
            "rmse": 0.1,
            "spearman_correlation": 0.8,
        },
        confidence_policy={"base_confidence": 0.95},
        training_provenance={
            "seed": 17,
            "ridge_alpha": 1.0,
            "holdout_test_fraction": 0.2,
            "eligibility_thresholds": {
                "minimum_observed_samples": 30,
                "minimum_independent_groups": 5,
                "maximum_holdout_mae": 0.25,
                "minimum_spearman_correlation": 0.3,
                "minimum_selection_confidence": 0.7,
                "maximum_ood_feature_ratio": 0.2,
            },
            "training_lineage_group_hashes": tuple(
                f"{index:x}" * 64 for index in range(1, 6)
            ),
        },
        artifact_hash="",
    ).with_computed_hash()
    PartitionRankerRepository(registry).save(artifact)
    return registry


def test_plan_cli_accepts_registered_model_version(tmp_path, capsys):
    input_path = _v2_input_path(tmp_path)
    registry = _ranker_registry(tmp_path)

    exit_code = main(
        [
            "plan-model-partition-v2",
            "--input",
            str(input_path),
            "--policy",
            POLICY,
            "--artifact-root",
            str(tmp_path / "artifacts"),
            "--selection-mode",
            "shadow",
            "--ranker-model-version",
            "partition-ridge-observed-v1",
            "--ranker-registry",
            str(registry),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["plan"]["selection"]["mode"] == "shadow"


def test_build_partition_ranking_dataset_cli_reports_observed_source(tmp_path, capsys):
    input_path = _v2_input_path(tmp_path)
    artifact_root = tmp_path / "artifacts"
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    run_partition_planning(
        payload,
        policy_path=POLICY,
        artifact_root=artifact_root,
        observed={
            "latency_ms": 120.0,
            "maximum_memory_pressure": 0.4,
            "total_transfer_bytes": 2048,
            "source": "runtime-monitor",
            "observed_at": "2026-08-21T09:30:00Z",
            "runtime_outcome_ref": "outcomes/cli-observed/versions/1/result",
        },
        plan_id_factory=lambda: "cli-observed",
        v2_request=True,
    )
    output = tmp_path / "dataset.jsonl"

    exit_code = main(
        [
            "build-partition-ranking-dataset",
            "--artifact-root",
            str(artifact_root),
            "--output",
            str(output),
            "--scope",
            "observed",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["scope"] == "observed"
    assert report["row_count"] == 1
    assert report["dataset_path"] == str(output.resolve())


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
    input_path = _infeasible_v2_input_path(tmp_path)
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

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_artifacts import write_partition_report
from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_evaluator import PartitionPlanEvaluator
from aiops_k8s_agents.partition_feedback import PartitionRuntimeFeedback
from aiops_k8s_agents.partition_features import FEATURE_ORDER
from aiops_k8s_agents.partition_learning import build_partition_ranking_dataset
from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionContractError,
)
from aiops_k8s_agents.partition_repository import PartitionPlanRepository
from aiops_k8s_agents.partition_ranker_repository import (
    VALIDATION_METRIC_KEYS,
    PartitionRankerModelArtifact,
    PartitionRankerRepository,
)
from aiops_k8s_agents.partition_service import (
    PartitionFeedbackService,
    run_partition_planning,
)
from aiops_k8s_agents.partition_validator import PartitionPlanValidator


ROOT = Path(__file__).resolve().parents[1]
SIGNING_KEY = "task-6-observed-artifact-signing-key"


@pytest.fixture(autouse=True)
def observed_artifact_signing_key(monkeypatch):
    monkeypatch.setenv("AIOPS_PARTITION_ARTIFACT_HMAC_KEY", SIGNING_KEY)


@pytest.fixture
def ranker_registry(tmp_path: Path) -> Path:
    registry = tmp_path / "ranker-registry"
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


def _observed_runtime_payload(plan_id: str) -> dict[str, object]:
    return {
        "latency_ms": 120.0,
        "maximum_memory_pressure": 0.4,
        "total_transfer_bytes": 2048,
        "source": "runtime-monitor",
        "observed_at": "2026-08-21T09:30:00Z",
        "runtime_outcome_ref": f"outcomes/{plan_id}/versions/1/result",
    }


def test_shadow_service_persists_baseline_and_learned_ranking(
    tmp_path: Path, ranker_registry: Path
):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["coordination_plan"]["payload"]["latency_slo_ms"] = 500.0
    payload["coordination_plan"]["payload"]["constraints"][
        "max_end_to_end_latency_ms"
    ] = 500.0

    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path / "artifacts",
        selection_mode="shadow",
        ranker_registry_root=ranker_registry,
        ranker_model_version="partition-ridge-observed-v1",
        plan_id_factory=lambda: "shadow-service-plan",
        v2_request=True,
    )

    selection = report["plan"]["selection"]
    assert selection["mode"] == "shadow"
    assert selection["final_selected_candidate_key"] == selection["baseline_selected_candidate_key"]
    assert (
        Path(report["artifact_path"]).parent
        / "versions"
        / "1"
        / "candidate_ranking.json"
    ).is_file()


def test_service_observed_runtime_outcome_is_transactional_and_dataset_eligible(
    tmp_path: Path,
):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["coordination_plan"]["payload"]["latency_slo_ms"] = 500.0
    payload["coordination_plan"]["payload"]["constraints"][
        "max_end_to_end_latency_ms"
    ] = 500.0
    artifact_root = tmp_path / "artifacts"
    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=artifact_root,
        observed=_observed_runtime_payload("observed-service-plan"),
        plan_id_factory=lambda: "observed-service-plan",
        v2_request=True,
    )

    metrics = report["evaluation"]["metrics"]
    runtime_outcome = (
        Path(report["artifact_path"]).parent
        / "versions"
        / "1"
        / "runtime_outcome.json"
    )
    assert report["evaluation"]["evidence_level"] == "observed"
    assert report["evaluation"]["estimated"] is False
    assert metrics["runtime_outcome_ref"] == "outcomes/observed-service-plan/versions/1/result"
    assert runtime_outcome.is_file()
    authenticated_manifest = runtime_outcome.with_name("authenticated_manifest.json")
    assert authenticated_manifest.is_file()
    assert set(json.loads(authenticated_manifest.read_text(encoding="utf-8"))["files"]) == {
        "report.json",
        "runtime_outcome.json",
        "candidate_ranking.json",
        "normalized_request.json",
        "partition_intent.json",
    }
    assert build_partition_ranking_dataset((artifact_root,), tmp_path / "dataset.jsonl").row_count == 1


def test_feedback_replan_preserves_selection_mode_and_exclusions(
    tmp_path: Path, ranker_registry: Path
):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["coordination_plan"]["payload"]["latency_slo_ms"] = 500.0
    payload["coordination_plan"]["payload"]["constraints"][
        "max_end_to_end_latency_ms"
    ] = 500.0
    repository = PartitionPlanRepository(tmp_path / "artifacts")
    initial = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=repository.root,
        selection_mode="shadow",
        ranker_registry_root=ranker_registry,
        ranker_model_version="partition-ridge-observed-v1",
        plan_id_factory=lambda: "shadow-feedback-v1",
        v2_request=True,
    )
    service = PartitionFeedbackService(
        repository,
        ROOT / "config/model_partition_policy.json",
        ranker_registry_root=ranker_registry,
        plan_id_factory=lambda: "shadow-feedback-v2",
    )

    report = service.process_feedback(
        initial["plan"]["plan_id"],
        {
            "signal": "placement_rejected",
            "source": "runtime-monitor",
            "reason": "runtime placement rejected the selected candidate",
            "received_at": "2026-08-21T10:00:00Z",
            "plan_id": initial["plan"]["plan_id"],
            "plan_version": initial["plan"]["plan_version"],
        },
    )

    assert report["plan"]["selection"]["mode"] == "shadow"
    assert report["replanning"]["bounded_exclusions"]["excluded_candidate_splits"]


@pytest.mark.parametrize("tamper", ("missing", "candidate", "plan", "ref", "metrics"))
def test_observed_dataset_rejects_tampered_runtime_outcome_sidecar(
    tmp_path: Path, tamper: str
):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["coordination_plan"]["payload"]["latency_slo_ms"] = 500.0
    payload["coordination_plan"]["payload"]["constraints"][
        "max_end_to_end_latency_ms"
    ] = 500.0
    artifact_root = tmp_path / "artifacts"
    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=artifact_root,
        observed=_observed_runtime_payload("tampered-service-plan"),
        plan_id_factory=lambda: "tampered-service-plan",
        v2_request=True,
    )
    runtime_outcome = (
        Path(report["artifact_path"]).parent
        / "versions"
        / "1"
        / "runtime_outcome.json"
    )
    if tamper == "missing":
        runtime_outcome.unlink()
    else:
        sidecar = json.loads(runtime_outcome.read_text(encoding="utf-8"))
        if tamper == "candidate":
            sidecar["selected_candidate_key"] = "forged-candidate"
        elif tamper == "plan":
            sidecar["plan_id"] = "forged-plan"
        elif tamper == "ref":
            sidecar["runtime_outcome_ref"] = "outcomes/forged/versions/1/result"
        else:
            sidecar["metrics"]["latency_ms"] = 1.0
        runtime_outcome.write_text(json.dumps(sidecar), encoding="utf-8")

    summary = build_partition_ranking_dataset((artifact_root,), tmp_path / "dataset.jsonl")

    assert summary.row_count == 0
    assert summary.rejections["authenticated_manifest_mismatch"] == 1


def test_partition_service_persists_same_validated_and_evaluated_plan(tmp_path):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )

    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
        plan_id_factory=lambda: "partition-service-plan",
    )
    stored = json.loads(Path(report["artifact_path"]).read_text(encoding="utf-8"))

    assert report["status"] == "planned"
    assert report["plan"]["selected_candidate"]["split_points"] == [3]
    assert report["validation"]["valid"] is True
    assert report["evaluation"]["evidence_level"] == "predicted"
    assert "estimated" in report["evaluation"]["label"].lower()
    assert stored["plan"] == report["plan"]
    assert stored["validation"] == report["validation"]
    assert stored["evaluation"] == report["evaluation"]
    artifact_directory = Path(report["artifact_path"]).parent
    version_directory = artifact_directory / "versions" / "1"
    assert (version_directory / "normalized_request.json").is_file()
    assert (version_directory / "partition_intent.json").is_file()
    handoff = json.loads(
        (version_directory / "scheduling_handoff.json").read_text(encoding="utf-8")
    )
    assert handoff["status"] == "blocked"
    assert handoff["scheduler_ref"] is None
    assert report["scheduling_handoff"] == handoff


def test_partition_service_supports_bounded_replanning(tmp_path):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    first = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
        plan_id_factory=lambda: "partition-first-plan",
    )

    second = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path,
        previous_plan_payload=first["plan"],
        failure_payload={"signal": "latency_slo_violation"},
        replan_attempt=1,
        plan_id_factory=lambda: "partition-second-plan",
    )

    assert second["plan"]["selected_candidate"]["split_points"] != [3]
    assert second["replanning"]["attempt"] == 1


def test_partition_service_persists_v2_requests_for_feedback(tmp_path):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["coordination_plan"]["payload"]["latency_slo_ms"] = 500.0
    payload["coordination_plan"]["payload"]["constraints"][
        "max_end_to_end_latency_ms"
    ] = 500.0

    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path / "repository",
        plan_id_factory=lambda: "partition-v2-service-plan",
    )

    assert report["status"] == "planned"
    assert report["planning_request"] == payload
    assert report["plan"]["plan_version"] == 1
    assert report["scheduling_handoff"]["status"] == "ready"
    assert PartitionPlanRepository(tmp_path / "repository").get(
        "partition-v2-service-plan"
    )["plan"] == report["plan"]


@pytest.fixture
def feedback_service(tmp_path):
    repository = PartitionPlanRepository(tmp_path / "feedback-repository")
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=repository.root,
        plan_id_factory=lambda: "partition-feedback-v1",
    )
    identifiers = iter(("partition-feedback-v2", "partition-feedback-v3", "partition-feedback-v4"))
    service = PartitionFeedbackService(
        repository,
        ROOT / "config/model_partition_policy.json",
        plan_id_factory=lambda: next(identifiers),
    )
    return service, report, repository


def _latency_feedback(report: dict) -> dict:
    return {
        "signal": "latency_slo_violation",
        "source": "runtime-monitor",
        "reason": "observed latency exceeded the approved SLO",
        "received_at": "2026-08-20T00:00:00+00:00",
        "plan_id": report["plan"]["plan_id"],
        "plan_version": report["plan"]["plan_version"],
    }


def test_feedback_replan_increments_version_and_links_parent(feedback_service):
    service, report_v1, _ = feedback_service

    report_v2 = service.process_feedback(
        report_v1["plan"]["plan_id"], _latency_feedback(report_v1)
    )

    assert report_v2["status"] == "planned"
    assert report_v2["plan"]["plan_version"] == 2
    assert report_v2["plan"]["parent_plan_id"] == report_v1["plan"]["plan_id"]
    assert report_v2["replanning"]["reason"] == "latency_slo_violation"
    assert report_v2["scheduling_handoff"]["status"] in {"ready", "blocked"}
    assert report_v2["scheduling_handoff"]["scheduler_ref"] is None


def test_feedback_replan_cumulatively_narrows_previous_candidates(feedback_service):
    service, report_v1, _ = feedback_service
    report_v2 = service.process_feedback(
        report_v1["plan"]["plan_id"], _latency_feedback(report_v1)
    )
    report_v3 = service.process_feedback(
        report_v2["plan"]["plan_id"], _latency_feedback(report_v2)
    )

    assert report_v3["status"] == "planned"
    assert report_v1["plan"]["selected_candidate"]["split_points"] != report_v3["plan"]["selected_candidate"]["split_points"]
    assert report_v2["plan"]["selected_candidate"]["split_points"] != report_v3["plan"]["selected_candidate"]["split_points"]


def test_feedback_replan_exhaustion_requires_human_review(feedback_service):
    service, report_v1, _ = feedback_service
    report_v2 = service.process_feedback(
        report_v1["plan"]["plan_id"], _latency_feedback(report_v1)
    )
    report_v3 = service.process_feedback(
        report_v2["plan"]["plan_id"], _latency_feedback(report_v2)
    )

    result = service.process_feedback(
        report_v3["plan"]["plan_id"], _latency_feedback(report_v3)
    )

    assert result["status"] == "blocked"
    assert result["plan"]["human_review_required"] is True
    assert "replan_attempts_exhausted" in result["plan"]["errors"]


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"source": ""}, "feedback_context_required"),
        ({"reason": ""}, "feedback_context_required"),
        ({"received_at": ""}, "feedback_context_required"),
        ({"plan_id": ""}, "feedback_context_required"),
        ({"plan_version": 0}, "feedback_context_required"),
        ({"signal": "unknown_signal"}, "unsupported_feedback_signal"),
        (
            {"signal": "device_unavailable", "device_id": ""},
            "feedback_context_required",
        ),
        (
            {"signal": "transfer_failure", "target_device": ""},
            "feedback_context_required",
        ),
    ],
)
@pytest.mark.parametrize("as_object", [False, True])
def test_feedback_service_revalidates_mapping_and_constructed_feedback(
    feedback_service, changes, expected_code, as_object
):
    service, report_v1, repository = feedback_service
    feedback = replace(
        PartitionRuntimeFeedback.from_dict(_latency_feedback(report_v1)), **changes
    )
    before = _artifact_snapshot(repository.root)
    feedback_input = feedback if as_object else feedback.to_dict()

    with pytest.raises(PartitionContractError) as error:
        service.process_feedback(report_v1["plan"]["plan_id"], feedback_input)

    assert error.value.code == expected_code
    assert _artifact_snapshot(repository.root) == before


def test_feedback_service_rejects_non_current_parent_before_replanning(feedback_service):
    service, report_v1, repository = feedback_service
    report_v2 = service.process_feedback(
        report_v1["plan"]["plan_id"], _latency_feedback(report_v1)
    )
    before = _artifact_snapshot(repository.root)

    with pytest.raises(PartitionContractError) as error:
        service.process_feedback(
            report_v1["plan"]["plan_id"], _latency_feedback(report_v1)
        )

    assert error.value.code == "non_current_feedback_plan"
    assert _artifact_snapshot(repository.root) == before
    assert [report["plan"]["plan_id"] for report in repository.history(
        report_v2["plan"]["plan_id"]
    )] == [report_v2["plan"]["plan_id"], report_v1["plan"]["plan_id"]]


def test_native_v2_training_feedback_replan_preserves_bounds_and_lineage(tmp_path):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_training_v2.json").read_text(
            encoding="utf-8"
        )
    )
    payload["system_context"]["model_structure_profile"]["blocks"].append(
        {
            "block_id": "classifier",
            "layer_names": ["classifier"],
            "parameter_bytes": 8_000_000,
            "activation_bytes": 1_000_000,
            "working_memory_bytes": 4_000_000,
        }
    )
    request = PartitionPlanningRequest.from_dict(payload)
    policy = ModelPartitionPolicy.from_path(ROOT / "config/model_partition_policy.json")
    agent = ModelPartitionOrchestrationAgent(
        policy, plan_id_factory=lambda: "partition-training-v1"
    )
    initial_plan = agent.plan_request(request)
    normalized = PartitionCommonProcessor().process(request)
    round_plan = FederatedRoundPlan(
        job_id=normalized.job_id,
        model_id=normalized.model_id,
        execution_mode=normalized.approved_execution_mode,
        layers=normalized.layers,
        participants=normalized.participants,
        devices=normalized.devices,
        network_links=normalized.network_links,
        constraints=normalized.constraints,
    )
    validation = PartitionPlanValidator().validate(request, initial_plan)
    repository = PartitionPlanRepository(tmp_path / "training-repository")
    report_v1 = {
        "schema_version": "1.0",
        "kind": "model_partition_orchestration",
        "status": "planned",
        "planning_request": payload,
        "round_plan": round_plan.to_dict(),
        "plan": initial_plan.to_dict(),
        "validation": validation.to_dict(),
        "evaluation": PartitionPlanEvaluator(policy).evaluate(
            round_plan, initial_plan, validation
        ).to_dict(),
        "replanning": None,
    }
    repository.save(report_v1)
    service = PartitionFeedbackService(
        repository,
        ROOT / "config/model_partition_policy.json",
        plan_id_factory=lambda: "partition-training-v2",
    )
    feedback = {
        "signal": "latency_slo_violation",
        "source": "training-runtime-monitor",
        "reason": "observed training latency exceeded the approved SLO",
        "received_at": "2026-08-20T00:00:00+00:00",
        "plan_id": initial_plan.plan_id,
        "plan_version": initial_plan.plan_version,
    }

    report_v2 = service.process_feedback(initial_plan.plan_id, feedback)

    assert validation.valid is True
    assert report_v2["status"] == "planned"
    assert report_v2["plan"]["plan_version"] == 2
    assert report_v2["plan"]["parent_plan_id"] == initial_plan.plan_id
    assert report_v2["plan"]["plan_type"] == "training"
    assert report_v2["round_plan"]["constraints"] == report_v1["round_plan"]["constraints"]
    assert set(
        partition["device_id"]
        for partition in report_v2["plan"]["selected_candidate"]["partitions"]
    ) == set(report_v1["round_plan"]["participants"])
    assert report_v2["plan"]["selected_candidate"]["split_points"] != report_v1[
        "plan"
    ]["selected_candidate"]["split_points"]


def test_artifact_writer_adds_a_blocked_handoff_for_existing_valid_reports(tmp_path):
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path / "service-artifacts",
        plan_id_factory=lambda: "partition-service-plan",
    )
    report.pop("scheduling_handoff")

    artifact_path = write_partition_report(report, tmp_path / "writer-artifacts")
    handoff = json.loads(
        (
            artifact_path.parent
            / "versions"
            / "1"
            / "scheduling_handoff.json"
        ).read_text(encoding="utf-8")
    )

    assert handoff["status"] == "blocked"
    assert handoff["scheduler_ref"] is None


def test_artifact_writer_replaces_a_forged_scheduler_claim(tmp_path):
    report = _planned_report(tmp_path / "source-artifacts", "partition-plan-v1")
    report["scheduling_handoff"] = {
        "handoff_id": "forged-handoff",
        "partition_plan_id": "partition-plan-v1",
        "partition_plan_version": 1,
        "created_at": "2026-08-20T00:00:00+00:00",
        "status": "scheduled",
        "scheduler_ref": "external-scheduler-run-7",
    }

    artifact_path = write_partition_report(report, tmp_path / "artifacts")
    persisted = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert persisted["scheduling_handoff"]["status"] == "blocked"
    assert persisted["scheduling_handoff"]["scheduler_ref"] is None
    assert report["scheduling_handoff"] == persisted["scheduling_handoff"]


def test_artifact_write_recovers_all_contract_files_after_interruption(
    tmp_path, monkeypatch
):
    artifact_root = tmp_path / "artifacts"
    parent = _planned_report(artifact_root, "partition-plan-v1")
    child = copy.deepcopy(parent)
    child.pop("artifact_path")
    child["plan"].update(
        {
            "plan_id": "partition-plan-v2",
            "plan_version": 2,
            "parent_plan_id": "partition-plan-v1",
        }
    )
    before = _artifact_snapshot(artifact_root)
    def interrupt_after_directory_replace(
        repository: PartitionPlanRepository, point: str
    ) -> None:
        if point == "after_plan_directory_replace":
            raise OSError("deterministic publication interruption")

    monkeypatch.setattr(
        PartitionPlanRepository, "_inject_fault", interrupt_after_directory_replace
    )

    with pytest.raises(OSError, match="deterministic publication interruption"):
        write_partition_report(child, artifact_root)

    PartitionPlanRepository(artifact_root)
    assert _artifact_snapshot(artifact_root) == before
    assert not (artifact_root / "partition-plan-v2").exists()


def test_repository_revalidates_a_report_despite_a_forged_valid_flag(tmp_path):
    report = _planned_report(tmp_path / "source-artifacts", "partition-plan-v1")
    report["plan"]["selected_candidate"]["split_points"] = [0]
    report["validation"]["valid"] = True
    repository = PartitionPlanRepository(tmp_path / "repository")

    with pytest.raises(PartitionContractError) as error:
        repository.save(report)

    assert error.value.code == "independent_validation_failed"


def test_repository_revalidates_a_v2_signature_despite_a_forged_valid_flag(
    tmp_path,
):
    report = _planned_report(tmp_path / "source-artifacts", "partition-plan-v1")
    report["plan"]["deterministic_signature"] = "0" * 64
    report["validation"]["valid"] = True
    repository = PartitionPlanRepository(tmp_path / "repository")

    with pytest.raises(PartitionContractError) as error:
        repository.save(report)

    assert error.value.code == "independent_validation_failed"


def test_permissive_validation_hook_cannot_authorize_an_invalid_v2_report(tmp_path):
    report = _planned_report(tmp_path / "source-artifacts", "partition-plan-v1")
    report["plan"]["deterministic_signature"] = "0" * 64
    repository = PartitionPlanRepository(tmp_path / "repository")
    repository._validation_runner = lambda _: True

    with pytest.raises(PartitionContractError) as error:
        repository.save(report)

    assert error.value.code == "independent_validation_failed"


def test_signed_blocked_report_preserves_only_legacy_artifact(tmp_path):
    report = _planned_report(tmp_path / "source-artifacts", "partition-plan-v1")
    report["status"] = "blocked"
    report["plan"]["valid"] = False
    report["validation"]["valid"] = False

    artifact_path = write_partition_report(report, tmp_path / "artifacts")

    assert artifact_path.is_file()
    assert not (artifact_path.parent / "versions").exists()


def _planned_report(artifact_root: Path, plan_id: str) -> dict:
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    return run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=artifact_root,
        plan_id_factory=lambda: plan_id,
    )


def _artifact_snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.json"))
    }

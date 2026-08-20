from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_artifacts import write_partition_report
from aiops_k8s_agents.partition_models import PartitionContractError
from aiops_k8s_agents.partition_repository import PartitionPlanRepository
from aiops_k8s_agents.partition_service import (
    PartitionFeedbackService,
    run_partition_planning,
)


ROOT = Path(__file__).resolve().parents[1]


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
    return PartitionFeedbackService(
        repository,
        ROOT / "config/model_partition_policy.json",
        plan_id_factory=lambda: next(identifiers),
    ), report


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
    service, report_v1 = feedback_service

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
    service, report_v1 = feedback_service
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
    service, report_v1 = feedback_service
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

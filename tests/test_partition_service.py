from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_artifacts import write_partition_report
from aiops_k8s_agents.partition_models import PartitionContractError
from aiops_k8s_agents.partition_repository import PartitionPlanRepository
from aiops_k8s_agents.partition_service import run_partition_planning


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


def test_artifact_write_rolls_back_all_contract_files_after_interruption(
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
    replace = Path.replace
    replace_calls = 0

    def interrupt_on_sixth_replace(path: Path, target: str | Path) -> Path:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 6:
            raise OSError("deterministic publication interruption")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", interrupt_on_sixth_replace)

    with pytest.raises(OSError, match="deterministic publication interruption"):
        write_partition_report(child, artifact_root)

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

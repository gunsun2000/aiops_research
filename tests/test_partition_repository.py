from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_models import PartitionContractError
from aiops_k8s_agents.partition_models import PartitionExecutionPlan
from aiops_k8s_agents.partition_repository import (
    PartitionPlanRepository,
    SchedulingHandoff,
)
from aiops_k8s_agents.partition_service import run_partition_planning


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def report_v1(tmp_path) -> dict:
    payload = json.loads(
        (ROOT / "config/examples/model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )
    report = run_partition_planning(
        payload,
        policy_path=ROOT / "config/model_partition_policy.json",
        artifact_root=tmp_path / "source-artifacts",
        plan_id_factory=lambda: "partition-plan-v1",
    )
    report.pop("artifact_path")
    return report


def test_repository_saves_versioned_plan_and_latest_pointer(tmp_path, report_v1):
    repository = _repository(tmp_path)

    saved = repository.save(report_v1)

    assert saved == tmp_path / "partition-plan-v1" / "versions" / "1" / "report.json"
    assert repository.get(report_v1["plan"]["plan_id"])["plan"]["plan_version"] == 1
    assert repository.history(report_v1["plan"]["plan_id"])[0]["plan"]["plan_version"] == 1


def test_repository_rejects_duplicate_version_with_different_signature(tmp_path, report_v1):
    repository = _repository(tmp_path)
    repository.save(report_v1)
    tampered = copy.deepcopy(report_v1)
    tampered["plan"]["deterministic_signature"] = "0" * 64

    with pytest.raises(PartitionContractError) as error:
        repository.save(tampered)

    assert error.value.code == "plan_version_conflict"


def test_repository_canonicalizes_a_forged_scheduling_handoff(tmp_path, report_v1):
    report_v1["scheduling_handoff"] = {
        "handoff_id": "forged-handoff",
        "partition_plan_id": "partition-plan-v1",
        "partition_plan_version": 1,
        "created_at": "2026-08-20T00:00:00+00:00",
        "status": "scheduled",
        "scheduler_ref": "external-scheduler-run-7",
    }
    repository = _repository(tmp_path)

    repository.save(report_v1)

    handoff = repository.get("partition-plan-v1")["scheduling_handoff"]
    assert handoff["status"] == "blocked"
    assert handoff["scheduler_ref"] is None


def test_repository_rejects_reserved_report_sidecar_name(tmp_path, report_v1):
    repository = _repository(tmp_path)

    with pytest.raises(PartitionContractError) as error:
        repository.save(report_v1, sidecars={"report.json": {"forged": True}})

    assert error.value.code == "reserved_sidecar_name"


@pytest.mark.parametrize(
    "sidecar_name",
    [
        "REPORT.JSON",
        "SCHEDULING_HANDOFF.JSON",
        "LATEST.JSON",
        "HISTORY.JSON",
        "COMMIT.JSON",
        "PENDING.JSON",
    ],
)
def test_repository_rejects_casefolded_reserved_sidecar_names(
    tmp_path, report_v1, sidecar_name
):
    repository = _repository(tmp_path)
    repository.save(report_v1)
    version_directory = tmp_path / "partition-plan-v1" / "versions" / "1"
    canonical_report = (version_directory / "report.json").read_text(encoding="utf-8")
    canonical_handoff = (version_directory / "scheduling_handoff.json").read_text(
        encoding="utf-8"
    )

    with pytest.raises(PartitionContractError) as error:
        repository.save(report_v1, sidecars={sidecar_name: {"forged": True}})

    assert error.value.code == "reserved_sidecar_name"
    assert (version_directory / "report.json").read_text(encoding="utf-8") == (
        canonical_report
    )
    assert (version_directory / "scheduling_handoff.json").read_text(
        encoding="utf-8"
    ) == canonical_handoff


def test_repository_rejects_casefolded_sidecar_path_collisions(tmp_path, report_v1):
    repository = _repository(tmp_path)

    with pytest.raises(PartitionContractError) as error:
        repository.save(
            report_v1,
            sidecars={
                "diagnostics/Result.json": {"first": True},
                "DIAGNOSTICS\\result.JSON": {"second": True},
            },
        )

    assert error.value.code == "sidecar_name_collision"


def test_repository_requires_a_unique_plan_id_for_each_persisted_version(
    tmp_path, report_v1
):
    repository = _repository(tmp_path)
    repository.save(report_v1)
    reused_plan_id = copy.deepcopy(report_v1)
    reused_plan_id["plan"]["plan_version"] = 2
    reused_plan_id["plan"]["deterministic_signature"] = "b" * 64

    with pytest.raises(PartitionContractError) as error:
        repository.save(reused_plan_id)

    assert error.value.code == "plan_id_reused"


def test_repository_history_follows_immediate_parent_plan_links(tmp_path, report_v1):
    repository = _repository(tmp_path)
    repository.save(report_v1)
    report_v2 = copy.deepcopy(report_v1)
    report_v2["plan"].update(
        {
            "plan_id": "partition-plan-v2",
            "plan_version": 2,
            "parent_plan_id": "partition-plan-v1",
        }
    )
    repository.save(report_v2)

    history = repository.history("partition-plan-v2")

    assert [item["plan"]["plan_id"] for item in history] == [
        "partition-plan-v2",
        "partition-plan-v1",
    ]


def test_repository_marks_only_the_lineage_leaf_as_current(tmp_path, report_v1):
    repository = _repository(tmp_path)
    repository.save(report_v1)
    report_v2 = copy.deepcopy(report_v1)
    report_v2["plan"].update(
        {
            "plan_id": "partition-plan-v2",
            "plan_version": 2,
            "parent_plan_id": "partition-plan-v1",
        }
    )
    repository.save(report_v2)

    assert repository.is_current_leaf("partition-plan-v1") is False
    assert repository.is_current_leaf("partition-plan-v2") is True


def test_repository_rejects_an_orphan_parent_plan(tmp_path, report_v1):
    repository = _repository(tmp_path)
    child = copy.deepcopy(report_v1)
    child["plan"].update(
        {
            "plan_id": "partition-plan-v2",
            "plan_version": 2,
            "parent_plan_id": "missing-plan",
        }
    )

    with pytest.raises(PartitionContractError) as error:
        repository.save(child)

    assert error.value.code == "orphan_parent_plan"


def test_repository_rejects_a_parent_that_skips_the_current_predecessor(
    tmp_path, report_v1
):
    repository = _repository(tmp_path)
    repository.save(report_v1)
    report_v2 = copy.deepcopy(report_v1)
    report_v2["plan"].update(
        {
            "plan_id": "partition-plan-v2",
            "plan_version": 2,
            "parent_plan_id": "partition-plan-v1",
        }
    )
    repository.save(report_v2)
    report_v3 = copy.deepcopy(report_v2)
    report_v3["plan"].update(
        {
            "plan_id": "partition-plan-v3",
            "plan_version": 3,
            "parent_plan_id": "partition-plan-v1",
        }
    )

    with pytest.raises(PartitionContractError) as error:
        repository.save(report_v3)

    assert error.value.code == "non_immediate_parent_plan"


def test_repository_rejects_a_second_child_for_the_current_predecessor(
    tmp_path, report_v1
):
    repository = _repository(tmp_path)
    repository.save(report_v1)
    report_v2 = copy.deepcopy(report_v1)
    report_v2["plan"].update(
        {
            "plan_id": "partition-plan-v2",
            "plan_version": 2,
            "parent_plan_id": "partition-plan-v1",
        }
    )
    repository.save(report_v2)
    forked_version = copy.deepcopy(report_v2)
    forked_version["plan"].update(
        {
            "plan_id": "partition-plan-v2-fork",
        }
    )

    with pytest.raises(PartitionContractError) as error:
        repository.save(forked_version)

    assert error.value.code == "non_immediate_parent_plan"


def test_repository_recovers_a_post_replace_crash_without_publishing_child(
    tmp_path, report_v1
):
    parent_repository = _repository(tmp_path)
    parent_repository.save(report_v1)
    child = copy.deepcopy(report_v1)
    child["plan"].update(
        {
            "plan_id": "partition-plan-v2",
            "plan_version": 2,
            "parent_plan_id": "partition-plan-v1",
        }
    )
    crashing_repository = _repository(tmp_path)

    def crash_after_replace(point: str) -> None:
        if point == "after_plan_directory_replace":
            raise OSError("deterministic post-replace interruption")

    crashing_repository._fault_injector = crash_after_replace
    with pytest.raises(OSError, match="deterministic post-replace interruption"):
        crashing_repository.save(child)

    recovered = _repository(tmp_path)
    assert recovered.get("partition-plan-v1")["plan"]["plan_version"] == 1
    with pytest.raises(PartitionContractError) as error:
        recovered.get("partition-plan-v2")
    assert error.value.code == "plan_not_found"


def test_repository_upgrades_a_legacy_directory_without_losing_legacy_artifacts(
    tmp_path, report_v1
):
    plan_directory = tmp_path / "partition-plan-v1"
    plan_directory.mkdir()
    (plan_directory / "report.json").write_text(
        json.dumps({"legacy": True}), encoding="utf-8"
    )
    (plan_directory / "legacy-evidence.json").write_text(
        json.dumps({"evidence": "preserved"}), encoding="utf-8"
    )
    repository = _repository(tmp_path)

    saved = repository.save(report_v1, include_legacy_report=True)

    assert saved.is_file()
    assert repository.get("partition-plan-v1")["plan"]["plan_version"] == 1
    assert json.loads((plan_directory / "report.json").read_text(encoding="utf-8"))["plan"][
        "plan_id"
    ] == "partition-plan-v1"
    assert json.loads(
        (plan_directory / "legacy-evidence.json").read_text(encoding="utf-8")
    ) == {"evidence": "preserved"}


def test_repository_default_upgrade_preserves_exact_legacy_report(
    tmp_path, report_v1
):
    plan_directory = tmp_path / "partition-plan-v1"
    plan_directory.mkdir()
    legacy_report = b'{\r\n  "legacy": true,\r\n  "format": "preserve exactly"\r\n}\r\n'
    (plan_directory / "report.json").write_bytes(legacy_report)
    repository = _repository(tmp_path)

    repository.save(report_v1)

    assert (plan_directory / "report.json").read_bytes() == legacy_report


@pytest.mark.parametrize(
    "fault_point", ["after_plan_directory_backup", "after_plan_directory_replace"]
)
def test_repository_recovers_a_legacy_upgrade_interruption_to_the_prior_view(
    tmp_path, report_v1, fault_point
):
    plan_directory = tmp_path / "partition-plan-v1"
    plan_directory.mkdir()
    legacy_report = {"legacy": True}
    (plan_directory / "report.json").write_text(
        json.dumps(legacy_report), encoding="utf-8"
    )
    (plan_directory / "legacy-evidence.json").write_text(
        json.dumps({"evidence": "preserved"}), encoding="utf-8"
    )
    crashing_repository = _repository(tmp_path)

    def crash_during_legacy_upgrade(point: str) -> None:
        if point == fault_point:
            raise OSError("deterministic legacy upgrade interruption")

    crashing_repository._fault_injector = crash_during_legacy_upgrade
    with pytest.raises(OSError, match="deterministic legacy upgrade interruption"):
        crashing_repository.save(report_v1, include_legacy_report=True)

    recovered = _repository(tmp_path)
    assert json.loads((plan_directory / "report.json").read_text(encoding="utf-8")) == (
        legacy_report
    )
    assert (plan_directory / "legacy-evidence.json").is_file()
    assert not (plan_directory / "latest.json").exists()
    assert not (plan_directory / "history.json").exists()
    assert not (plan_directory / "commit.json").exists()
    with pytest.raises(PartitionContractError) as error:
        recovered.get("partition-plan-v1")
    assert error.value.code == "plan_not_found"


def test_scheduling_handoff_is_a_ready_read_only_projection():
    plan = PartitionExecutionPlan(
        plan_id="partition-plan-v1",
        job_id="job-1",
        model_id="model-1",
        approved_execution_mode="inference",
        policy_version="policy-1",
        selected_candidate=None,
        alternative_candidates=(),
        rationale="validated",
        valid=True,
        human_review_required=False,
        errors=(),
        handoff_status="ready",
    )

    handoff = SchedulingHandoff.create(
        plan,
        id_factory=lambda: "handoff-1",
        clock=lambda: "2026-08-20T00:00:00+00:00",
    )

    assert handoff.status == "ready"
    assert handoff.scheduler_ref is None
    assert handoff.to_dict()["partition_plan_id"] == "partition-plan-v1"


def test_scheduling_handoff_blocks_a_plan_without_ready_handoff_status():
    plan = PartitionExecutionPlan.safe_failure(
        plan_id="partition-plan-v1",
        job_id="job-1",
        model_id="model-1",
        approved_execution_mode="inference",
        policy_version="policy-1",
        errors=("validation_failed",),
    )

    handoff = SchedulingHandoff.create(
        plan,
        id_factory=lambda: "handoff-1",
        clock=lambda: "2026-08-20T00:00:00+00:00",
    )

    assert handoff.status == "blocked"
    assert handoff.scheduler_ref is None


def _repository(tmp_path):
    return PartitionPlanRepository(tmp_path)

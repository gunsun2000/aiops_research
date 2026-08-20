from __future__ import annotations

import copy

import pytest

from aiops_k8s_agents.partition_models import PartitionContractError
from aiops_k8s_agents.partition_models import PartitionExecutionPlan
from aiops_k8s_agents.partition_repository import (
    PartitionPlanRepository,
    SchedulingHandoff,
)


@pytest.fixture
def report_v1() -> dict:
    return {
        "schema_version": "1.0",
        "kind": "model_partition_orchestration",
        "status": "planned",
        "plan": {
            "plan_id": "partition-plan-v1",
            "plan_version": 1,
            "parent_plan_id": None,
            "valid": True,
            "deterministic_signature": "a" * 64,
        },
        "validation": {"valid": True},
    }


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
            "deterministic_signature": "b" * 64,
        }
    )
    repository.save(report_v2)

    history = repository.history("partition-plan-v2")

    assert [item["plan"]["plan_id"] for item in history] == [
        "partition-plan-v2",
        "partition-plan-v1",
    ]


def test_repository_rejects_an_orphan_parent_plan(tmp_path, report_v1):
    repository = _repository(tmp_path)
    child = copy.deepcopy(report_v1)
    child["plan"].update(
        {
            "plan_id": "partition-plan-v2",
            "plan_version": 2,
            "parent_plan_id": "missing-plan",
            "deterministic_signature": "b" * 64,
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
            "deterministic_signature": "b" * 64,
        }
    )
    repository.save(report_v2)
    report_v3 = copy.deepcopy(report_v2)
    report_v3["plan"].update(
        {
            "plan_id": "partition-plan-v3",
            "plan_version": 3,
            "parent_plan_id": "partition-plan-v1",
            "deterministic_signature": "c" * 64,
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
            "deterministic_signature": "b" * 64,
        }
    )
    repository.save(report_v2)
    forked_version = copy.deepcopy(report_v2)
    forked_version["plan"].update(
        {
            "plan_id": "partition-plan-v2-fork",
            "deterministic_signature": "c" * 64,
        }
    )

    with pytest.raises(PartitionContractError) as error:
        repository.save(forked_version)

    assert error.value.code == "non_immediate_parent_plan"


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
    return PartitionPlanRepository(tmp_path, validation_runner=lambda report: True)

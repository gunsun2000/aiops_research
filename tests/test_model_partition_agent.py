from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionFailure,
)
from aiops_k8s_agents.partition_ranking import GuardedCandidateSelector
from aiops_k8s_agents.partition_ranking_models import SelectionMode


ROOT = Path(__file__).resolve().parents[1]


def example_payload() -> dict:
    return json.loads(
        (ROOT / "config" / "examples" / "model_partition_job.json").read_text(
            encoding="utf-8"
        )
    )


def example_round_plan() -> FederatedRoundPlan:
    return FederatedRoundPlan.from_dict(example_payload())


def example_policy() -> ModelPartitionPolicy:
    return ModelPartitionPolicy.from_path(
        ROOT / "config" / "model_partition_policy.json"
    )


def agent() -> ModelPartitionOrchestrationAgent:
    return ModelPartitionOrchestrationAgent(
        example_policy(), plan_id_factory=lambda: "partition-plan-test"
    )


@pytest.fixture
def orchestrator() -> ModelPartitionOrchestrationAgent:
    return agent()


@pytest.fixture
def inference_request() -> PartitionPlanningRequest:
    payload = json.loads(
        (ROOT / "config" / "examples" / "model_partition_inference_v2.json").read_text(
            encoding="utf-8"
        )
    )
    return PartitionPlanningRequest.from_dict(payload)


@pytest.fixture
def policy_path() -> Path:
    return ROOT / "config" / "model_partition_policy.json"


def test_v2_plan_records_strategy_snapshot_and_signature(
    orchestrator, inference_request
):
    plan = orchestrator.plan_request(inference_request)

    assert plan.plan_version == 1
    assert plan.parent_plan_id is None
    assert plan.plan_type == "inference"
    assert plan.strategy_id == "inference-partition-v1"
    assert len(plan.input_snapshot_hash) == 64
    assert len(plan.deterministic_signature) == 64
    assert 0.0 <= plan.confidence <= 1.0


def test_v2_plan_signature_is_stable_for_identical_selection_provenance(
    orchestrator, inference_request
):
    first = orchestrator.plan_request(inference_request)
    second = orchestrator.plan_request(inference_request)

    assert first.selection is not None
    assert second.selection is not None
    assert first.selection.mode == "deterministic"
    assert first.selection.active_ranker_version == "1.0"
    assert first.selection.model_artifact_hash is None
    assert first.selection.final_selected_candidate_key is not None
    assert first.deterministic_signature == second.deterministic_signature


def test_default_agent_plan_keeps_legacy_deterministic_selection(policy_path):
    plan = ModelPartitionOrchestrationAgent(
        ModelPartitionPolicy.from_path(policy_path)
    ).plan(example_round_plan())

    assert plan.selected_candidate is not None
    assert plan.selected_candidate.split_points == (3,)
    assert plan.selection is not None
    assert plan.selection.mode == "deterministic"


def test_agent_passes_shadow_mode_to_the_configured_selector(policy_path):
    selector = _ModeCapturingSelector()
    plan = ModelPartitionOrchestrationAgent(
        ModelPartitionPolicy.from_path(policy_path),
        selector=selector,
        selection_mode=SelectionMode.SHADOW,
        ranker_model_version="ranker-observed-v1",
    ).plan(example_round_plan())

    assert plan.selection is not None
    assert selector.mode is SelectionMode.SHADOW
    assert selector.model_version == "ranker-observed-v1"


class _ModeCapturingSelector(GuardedCandidateSelector):
    def __init__(self) -> None:
        super().__init__()
        self.mode: SelectionMode | None = None
        self.model_version: str | None = None

    def select(self, context, candidates, mode=SelectionMode.DETERMINISTIC, model_version=None):
        self.mode = mode
        self.model_version = model_version
        return super().select(context, candidates, mode, model_version)


def test_planner_selects_lowest_scored_feasible_split():
    plan = agent().plan(example_round_plan())

    assert plan.valid is True
    assert plan.selected_candidate is not None
    assert plan.selected_candidate.split_points == (3,)
    assert [partition.device_id for partition in plan.selected_candidate.partitions] == [
        "edge-cpu-01",
        "gpu-worker-01",
    ]
    assert tuple(
        layer
        for partition in plan.selected_candidate.partitions
        for layer in partition.layer_names
    ) == tuple(layer.name for layer in example_round_plan().layers)
    assert len(plan.alternative_candidates) == 4


def test_planner_builds_resource_estimates_and_execution_graph():
    selected = agent().plan(example_round_plan()).selected_candidate

    assert selected is not None
    assert selected.estimated_compute_ms == 450.0
    assert selected.estimated_transfer_ms == 12.0
    assert selected.estimated_total_latency_ms == 462.0
    assert selected.total_transfer_bytes == 100_000
    assert selected.graph_edges[0].source_partition == "partition-1"
    assert selected.graph_edges[0].target_partition == "partition-2"


def test_planner_records_memory_overflow_rejection_reasons():
    payload = example_payload()
    payload["devices"][0]["memory_available_bytes"] = 30_000_000
    round_plan = FederatedRoundPlan.from_dict(payload)

    plan = agent().plan(round_plan)

    assert plan.valid is True
    assert any(
        reason.startswith("memory_capacity_exceeded:edge-cpu-01")
        for candidate in plan.alternative_candidates
        for reason in candidate.rejection_reasons
    )


def test_planner_returns_safe_failure_when_no_candidate_is_feasible():
    payload = example_payload()
    for device in payload["devices"]:
        device["memory_available_bytes"] = 1_000_000
    round_plan = FederatedRoundPlan.from_dict(payload)

    plan = agent().plan(round_plan)

    assert plan.valid is False
    assert plan.selected_candidate is None
    assert plan.human_review_required is True
    assert plan.errors == ("no_feasible_partition",)


def test_latency_replan_excludes_previous_split_and_selects_next_candidate():
    planner = agent()
    round_plan = example_round_plan()
    previous = planner.plan(round_plan)

    replanned = planner.replan(
        round_plan,
        previous,
        PartitionFailure(signal="latency_slo_violation"),
        attempt=1,
    )

    assert previous.selected_candidate is not None
    assert replanned.selected_candidate is not None
    assert replanned.selected_candidate.split_points != previous.selected_candidate.split_points
    assert replanned.valid is True


def test_legacy_replan_adapter_retains_the_legacy_identity_shape():
    planner = agent()
    round_plan = example_round_plan()

    replanned = planner.replan(
        round_plan,
        planner.plan(round_plan),
        PartitionFailure(signal="latency_slo_violation"),
        attempt=1,
    )

    assert replanned.plan_version == 1
    assert replanned.parent_plan_id is None
    assert replanned.deterministic_signature == ""


def test_device_failure_with_two_participants_returns_safe_failure():
    planner = agent()
    round_plan = example_round_plan()

    replanned = planner.replan(
        round_plan,
        planner.plan(round_plan),
        PartitionFailure(signal="device_unavailable", device_id="edge-cpu-01"),
        attempt=1,
    )

    assert replanned.valid is False
    assert replanned.human_review_required is True
    assert "insufficient_participants_after_failure" in replanned.errors


def test_legacy_memory_failure_for_an_unselected_device_remains_fail_closed():
    planner = agent()
    round_plan = example_round_plan()

    replanned = planner.replan(
        round_plan,
        planner.plan(round_plan),
        PartitionFailure(signal="memory_exceeded", device_id="missing-device"),
        attempt=1,
    )

    assert replanned.valid is False
    assert replanned.errors == ("failed_device_not_in_previous_plan",)


def test_replanning_attempt_limit_is_fail_closed():
    planner = agent()
    round_plan = example_round_plan()

    replanned = planner.replan(
        round_plan,
        planner.plan(round_plan),
        PartitionFailure(signal="latency_slo_violation"),
        attempt=3,
    )

    assert replanned.valid is False
    assert replanned.errors == ("replan_attempts_exhausted",)


def test_identical_input_produces_identical_candidate_order_and_scores():
    first = agent().plan(example_round_plan()).to_dict()
    second = agent().plan(example_round_plan()).to_dict()

    assert first == second

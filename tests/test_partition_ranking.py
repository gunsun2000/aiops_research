from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_models import (
    ExecutionGraphNode,
    LogicalPartition,
    PartitionCandidate,
)
from aiops_k8s_agents.partition_ranking import (
    DeterministicPolicyRanker,
    RankingContext,
    candidate_key,
)
from aiops_k8s_agents.partition_ranking_models import SelectionMode
from aiops_k8s_agents.partition_strategies import PartitionStrategyRegistry


ROOT = Path(__file__).resolve().parents[1]


def _candidate(split_point: int, score: float) -> PartitionCandidate:
    partition = LogicalPartition(
        partition_id=f"partition-{split_point}",
        device_id="gpu-worker-01",
        layer_names=(f"layer-{split_point}",),
        compute_units=100.0,
        memory_demand_bytes=1_000,
    )
    return PartitionCandidate(
        split_points=(split_point,),
        partitions=(partition,),
        graph_nodes=(ExecutionGraphNode(partition.partition_id, partition.device_id),),
        graph_edges=(),
        estimated_compute_ms=100.0,
        estimated_transfer_ms=10.0,
        estimated_total_latency_ms=110.0,
        total_transfer_bytes=1_000,
        maximum_memory_pressure=0.1,
        valid=True,
        rejection_reasons=(),
        score=score,
    )


@pytest.fixture
def training_context() -> RankingContext:
    payload = json.loads(
        (ROOT / "config" / "examples" / "model_partition_training_v2.json").read_text(
            encoding="utf-8"
        )
    )
    request = PartitionPlanningRequest.from_dict(payload)
    normalized = PartitionCommonProcessor().process(request)
    strategy = PartitionStrategyRegistry.default().resolve(
        normalized.plan_type, normalized.approved_execution_mode.name
    )
    intent = strategy.build_partition_intent(normalized)
    return RankingContext(
        request=normalized,
        intent=intent,
        strategy_version=intent.strategy_version,
    )


@pytest.fixture
def candidates() -> tuple[PartitionCandidate, PartitionCandidate]:
    return (_candidate(1, 0.4), _candidate(3, 0.2))


def test_deterministic_ranker_preserves_existing_candidate_order(
    training_context, candidates
):
    ranking = DeterministicPolicyRanker().rank(training_context, candidates)

    assert ranking.baseline_selected_candidate_key == candidate_key(
        candidates[1], training_context.strategy_version
    )
    assert ranking.final_selected_candidate_key == ranking.baseline_selected_candidate_key
    assert ranking.mode is SelectionMode.DETERMINISTIC
    assert ranking.fallback_used is False


def test_invalid_candidate_is_never_rank_eligible(training_context, candidates):
    invalid = replace(candidates[0], valid=False, rejection_reasons=("memory_exceeded",))

    ranking = DeterministicPolicyRanker().rank(training_context, (invalid, candidates[1]))
    entry = next(
        item
        for item in ranking.entries
        if item.candidate_key
        == candidate_key(invalid, training_context.strategy_version)
    )

    assert entry.eligible is False
    assert ranking.final_selected_candidate_key != entry.candidate_key

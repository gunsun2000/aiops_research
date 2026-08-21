from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_context import canonical_json
from aiops_k8s_agents.partition_context import WorkloadForecast
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_features import (
    FEATURE_ORDER,
    candidate_key,
    extract_partition_features,
)
from aiops_k8s_agents.partition_models import (
    ExecutionGraphNode,
    LogicalPartition,
    PartitionCandidate,
    PartitionContractError,
)
from aiops_k8s_agents.partition_ranking import CandidateRanker, RankingContext
from aiops_k8s_agents.partition_ranking_models import CandidateSelection
from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_strategies import PartitionStrategyRegistry


ROOT = Path(__file__).resolve().parents[1]


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
    return RankingContext(
        request=normalized,
        intent=strategy.build_partition_intent(normalized),
        strategy_version="training-partition-v1:policy-v2",
    )


@pytest.fixture
def candidate() -> PartitionCandidate:
    partition = LogicalPartition(
        partition_id="partition-1",
        device_id="gpu-worker-01",
        layer_names=("embedding",),
        compute_units=100.0,
        memory_demand_bytes=1_000,
    )
    return PartitionCandidate(
        split_points=(1,),
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
        score=0.25,
        estimated_step_time_ms=120.0,
        gradient_transfer_bytes=500,
        maximum_load_imbalance=0.05,
        predicted_resilience_risk=0.2,
    )


def test_candidate_key_is_stable_and_excludes_plan_identity(training_context, candidate):
    expected_payload = {
        "split_points": [1],
        "assignments": [
            {"partition_id": "partition-1", "device_id": "gpu-worker-01"}
        ],
        "strategy_version": training_context.strategy_version,
    }
    expected = hashlib.sha256(
        canonical_json(expected_payload).encode("utf-8")
    ).hexdigest()

    first = candidate_key(candidate, training_context.strategy_version)
    second = candidate_key(
        replace(candidate, score=999.0, valid=False, rejection_reasons=("rejected",)),
        training_context.strategy_version,
    )

    assert first == expected
    assert second == expected
    assert len(first) == 64


def test_feature_vector_matches_declared_order(training_context, candidate):
    vector = extract_partition_features(training_context, candidate)

    assert tuple(vector) == FEATURE_ORDER
    assert all(math.isfinite(value) for value in vector.values())
    assert vector["plan_type_training"] == 1.0
    assert vector["plan_type_inference"] == 0.0
    assert vector["forecast_batch_size"] == 16.0
    assert vector["forecast_batch_size_missing"] == 0.0
    assert vector["candidate_partition_count"] == len(candidate.partitions)


def test_feature_vector_uses_zeroes_and_indicators_for_missing_forecast(
    training_context, candidate
):
    vector = extract_partition_features(
        replace(
            training_context,
            request=replace(training_context.request, workload_forecast=None),
            workload_forecast=None,
        ),
        candidate,
    )

    assert vector["forecast_request_rate"] == 0.0
    assert vector["forecast_batch_size"] == 0.0
    assert vector["forecast_sequence_length"] == 0.0
    assert vector["forecast_uncertainty"] == 0.0
    assert vector["forecast_request_rate_missing"] == 1.0
    assert vector["forecast_batch_size_missing"] == 1.0
    assert vector["forecast_sequence_length_missing"] == 1.0


def test_ranking_context_rejects_a_forecast_that_differs_from_the_normalized_request(
    training_context,
):
    conflicting_forecast = WorkloadForecast(
        forecast_id="different-forecast",
        horizon_seconds=60,
        expected_request_rate=1.0,
        expected_batch_size=1,
        expected_sequence_length=1,
        uncertainty=0.0,
        source="test",
    )

    with pytest.raises(PartitionContractError, match="workload_forecast"):
        replace(training_context, workload_forecast=conflicting_forecast)


def test_feature_extraction_rejects_negative_candidate_byte_sizes(
    training_context, candidate
):
    with pytest.raises(PartitionContractError, match="byte"):
        extract_partition_features(
            training_context, replace(candidate, total_transfer_bytes=-1)
        )


def test_default_orchestration_context_uses_normalized_forecast_for_features():
    payload = json.loads(
        (ROOT / "config" / "examples" / "model_partition_training_v2.json").read_text(
            encoding="utf-8"
        )
    )
    request = PartitionPlanningRequest.from_dict(payload)
    ranker = _ForecastCapturingRanker()
    policy = ModelPartitionPolicy.from_path(ROOT / "config" / "model_partition_policy.json")

    ModelPartitionOrchestrationAgent(policy, ranker=ranker).plan_request(request)

    assert ranker.forecast_batch_sizes == [16.0]


class _ForecastCapturingRanker(CandidateRanker):
    def __init__(self) -> None:
        self.forecast_batch_sizes: list[float] = []

    def rank(self, context: RankingContext, candidates) -> CandidateSelection:
        self.forecast_batch_sizes.append(
            extract_partition_features(context, candidates[0])["forecast_batch_size"]
        )
        from aiops_k8s_agents.partition_ranking import DeterministicPolicyRanker

        return DeterministicPolicyRanker().rank(context, candidates)

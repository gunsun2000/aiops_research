from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import aiops_k8s_agents.partition_ranking as partition_ranking
from aiops_k8s_agents.partition_common import PartitionCommonProcessor
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from aiops_k8s_agents.partition_models import (
    ExecutionGraphNode,
    LogicalPartition,
    PartitionCandidate,
)
from aiops_k8s_agents.partition_ranking import (
    DeterministicPolicyRanker,
    GuardedCandidateSelector,
    LearnedRankerGuardPolicy,
    LearnedRewardRanker,
    RankingContext,
    candidate_key,
)
from aiops_k8s_agents.partition_ranker_repository import PartitionRankerModelArtifact
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


@pytest.fixture
def eligible_artifact() -> PartitionRankerModelArtifact:
    return PartitionRankerModelArtifact(
        schema_version="partition-ranker-model-v1",
        model_type="ridge_reward_regressor",
        model_version="ranker-observed-v1",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        trained_at="2026-08-21T00:00:00Z",
        training_dataset_hash="b" * 64,
        training_scope="observed",
        sample_count=30,
        group_count=5,
        feature_order=FEATURE_ORDER,
        feature_mean=tuple(0.0 for _ in FEATURE_ORDER),
        feature_scale=tuple(1.0 for _ in FEATURE_ORDER),
        coefficients=tuple(
            1.0 if name == "baseline_score" else 0.0 for name in FEATURE_ORDER
        ),
        intercept=0.0,
        training_feature_ranges={name: (0.0, 10_000_000_000.0) for name in FEATURE_ORDER},
        validation_metrics={"holdout_mae": 0.10, "spearman_correlation": 0.80},
        confidence_policy={"base_confidence": 0.95},
        artifact_hash="",
    ).with_computed_hash()


@pytest.fixture
def guard_policy() -> LearnedRankerGuardPolicy:
    return LearnedRankerGuardPolicy(
        minimum_observed_samples=30,
        minimum_independent_groups=5,
        maximum_holdout_mae=0.25,
        minimum_spearman_correlation=0.30,
        minimum_selection_confidence=0.70,
        maximum_ood_feature_ratio=0.20,
    )


def guarded_selector(
    artifact: PartitionRankerModelArtifact, guard_policy: LearnedRankerGuardPolicy
) -> GuardedCandidateSelector:
    return GuardedCandidateSelector(
        deterministic=DeterministicPolicyRanker(),
        learned=LearnedRewardRanker(artifact),
        guard_policy=guard_policy,
    )


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


def test_shadow_records_learned_choice_but_keeps_baseline(
    training_context, candidates, eligible_artifact, guard_policy
):
    selection = guarded_selector(eligible_artifact, guard_policy).select(
        training_context, candidates, SelectionMode.SHADOW
    )

    assert selection.learned_selected_candidate_key == candidate_key(
        candidates[0], training_context.strategy_version
    )
    assert selection.final_selected_candidate_key == selection.baseline_selected_candidate_key
    assert selection.fallback_used is False


def test_guarded_mode_falls_back_when_model_has_too_few_observed_samples(
    training_context, candidates, eligible_artifact, guard_policy
):
    undertrained_artifact = replace(
        eligible_artifact, sample_count=29, artifact_hash=""
    ).with_computed_hash()

    selection = guarded_selector(undertrained_artifact, guard_policy).select(
        training_context, candidates, SelectionMode.LEARNED_GUARDED
    )

    assert selection.final_selected_candidate_key == selection.baseline_selected_candidate_key
    assert selection.fallback_used is True
    assert selection.fallback_reason == "insufficient_observed_samples"


@pytest.mark.parametrize(
    "artifact_changes",
    (
        pytest.param(
            {"model_type": "random_forest_reward_regressor"},
            id="unsupported-model-type",
        ),
        pytest.param(
            {"training_scope": "offline-evaluation"},
            id="non-observed-training-scope",
        ),
    ),
)
def test_guarded_mode_falls_back_for_non_deployment_artifact(
    training_context,
    candidates,
    eligible_artifact,
    guard_policy,
    artifact_changes,
):
    artifact = replace(
        eligible_artifact, **artifact_changes, artifact_hash=""
    ).with_computed_hash()

    selection = guarded_selector(artifact, guard_policy).select(
        training_context, candidates, SelectionMode.LEARNED_GUARDED
    )

    assert selection.final_selected_candidate_key == selection.baseline_selected_candidate_key
    assert selection.fallback_used is True
    assert selection.fallback_reason == "model_unavailable"


def test_guarded_mode_falls_back_when_features_are_out_of_distribution(
    training_context, candidates, eligible_artifact, guard_policy
):
    shifted_artifact = replace(
        eligible_artifact,
        training_feature_ranges={name: (0.0, 0.0) for name in FEATURE_ORDER},
        artifact_hash="",
    ).with_computed_hash()

    selection = guarded_selector(shifted_artifact, guard_policy).select(
        training_context, candidates, SelectionMode.LEARNED_GUARDED
    )

    assert selection.final_selected_candidate_key == selection.baseline_selected_candidate_key
    assert selection.fallback_used is True
    assert selection.fallback_reason == "feature_distribution_shift"


def test_guarded_mode_falls_back_at_ood_policy_boundary(
    training_context, candidates, eligible_artifact, guard_policy, monkeypatch
):
    monkeypatch.setattr(partition_ranking, "_ood_feature_ratio", lambda *_: 0.20)

    selection = guarded_selector(eligible_artifact, guard_policy).select(
        training_context, candidates, SelectionMode.LEARNED_GUARDED
    )

    assert selection.final_selected_candidate_key == selection.baseline_selected_candidate_key
    assert selection.fallback_used is True
    assert selection.fallback_reason == "feature_distribution_shift"


def test_learned_ranker_never_receives_hard_invalid_candidate(
    training_context, candidates, eligible_artifact, guard_policy
):
    invalid = replace(candidates[0], valid=False, rejection_reasons=("memory_exceeded",))

    selection = guarded_selector(eligible_artifact, guard_policy).select(
        training_context,
        (invalid, candidates[1]),
        SelectionMode.LEARNED_GUARDED,
    )
    invalid_key = candidate_key(invalid, training_context.strategy_version)
    invalid_entry = next(
        entry for entry in selection.entries if entry.candidate_key == invalid_key
    )

    assert invalid_entry.eligible is False
    assert invalid_entry.predicted_reward is None


def test_guarded_mode_falls_back_when_selected_prediction_has_low_confidence(
    training_context, candidates, eligible_artifact, guard_policy
):
    low_confidence_artifact = replace(
        eligible_artifact,
        confidence_policy={"base_confidence": 0.69},
        artifact_hash="",
    ).with_computed_hash()

    selection = guarded_selector(low_confidence_artifact, guard_policy).select(
        training_context, candidates, SelectionMode.LEARNED_GUARDED
    )

    assert selection.fallback_used is True
    assert selection.fallback_reason == "selection_confidence_below_threshold"

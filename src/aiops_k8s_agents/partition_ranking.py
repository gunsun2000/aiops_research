from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Protocol, Sequence

from aiops_k8s_agents.partition_common import NormalizedPartitionRequest
from aiops_k8s_agents.partition_context import canonical_json
from aiops_k8s_agents.partition_models import PartitionCandidate
from aiops_k8s_agents.partition_ranking_models import (
    CandidateRankingEntry,
    CandidateSelection,
    SelectionMode,
)
from aiops_k8s_agents.partition_strategies import PartitionIntent


@dataclass(frozen=True)
class RankingContext:
    request: NormalizedPartitionRequest
    intent: PartitionIntent
    strategy_version: str


class CandidateRanker(Protocol):
    def rank(
        self,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
    ) -> CandidateSelection: ...


class DeterministicPolicyRanker:
    ranker_id = "deterministic-policy-ranker"
    ranker_version = "1.0"
    feature_schema_version = "partition-feature-v1"

    def rank(
        self,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
    ) -> CandidateSelection:
        ordered = tuple(
            sorted(
                candidates,
                key=lambda item: (not item.valid, item.score, item.split_points),
            )
        )
        selected = next((item for item in ordered if item.valid), None)
        return selection_from_deterministic_order(context, ordered, selected)


class GuardedCandidateSelector:
    def __init__(self, ranker: CandidateRanker) -> None:
        self._ranker = ranker

    def select(
        self,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
    ) -> CandidateSelection:
        selection = self._ranker.rank(context, candidates)
        valid_keys = {
            candidate_key(candidate, context.strategy_version)
            for candidate in candidates
            if candidate.valid
        }
        if selection.final_selected_candidate_key in valid_keys or not valid_keys:
            return selection

        fallback_key = selection.baseline_selected_candidate_key
        if fallback_key not in valid_keys:
            fallback_key = next(
                candidate_key(candidate, context.strategy_version)
                for candidate in candidates
                if candidate.valid
            )
        return replace(
            selection,
            final_selected_candidate_key=fallback_key,
            fallback_used=True,
            fallback_reason="final_selection_not_rank_eligible",
        )


def candidate_key(candidate: PartitionCandidate, strategy_version: str) -> str:
    payload = {
        "candidate": candidate.to_dict(),
        "strategy_version": strategy_version,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"partition-candidate-v1:{digest}"


def selection_from_deterministic_order(
    context: RankingContext,
    ordered: Sequence[PartitionCandidate],
    selected: PartitionCandidate | None,
) -> CandidateSelection:
    selected_key = (
        None
        if selected is None
        else candidate_key(selected, context.strategy_version)
    )
    return CandidateSelection(
        mode=SelectionMode.DETERMINISTIC,
        active_ranker_id=DeterministicPolicyRanker.ranker_id,
        active_ranker_version=DeterministicPolicyRanker.ranker_version,
        baseline_selected_candidate_key=selected_key,
        learned_selected_candidate_key=None,
        final_selected_candidate_key=selected_key,
        model_version=None,
        model_artifact_hash=None,
        feature_schema_version=DeterministicPolicyRanker.feature_schema_version,
        entries=tuple(
            CandidateRankingEntry(
                candidate_key=candidate_key(candidate, context.strategy_version),
                baseline_score=candidate.score,
                predicted_reward=None,
                prediction_confidence=None,
                rank=index,
                eligible=candidate.valid,
                warnings=candidate.rejection_reasons,
            )
            for index, candidate in enumerate(ordered, start=1)
        ),
        confidence=1.0,
        fallback_used=False,
        fallback_reason=None,
        rationale=(
            "Deterministic policy orders valid candidates by score and split points.",
        ),
    )

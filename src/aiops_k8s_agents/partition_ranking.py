from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Mapping, Protocol, Sequence

from aiops_k8s_agents.partition_common import NormalizedPartitionRequest
from aiops_k8s_agents.partition_context import WorkloadForecast
from aiops_k8s_agents.partition_features import (
    FEATURE_ORDER,
    FEATURE_SCHEMA_VERSION,
    candidate_key,
    extract_partition_features,
)
from aiops_k8s_agents.partition_models import PartitionCandidate, PartitionContractError
from aiops_k8s_agents.partition_ranker_repository import PartitionRankerModelArtifact
from aiops_k8s_agents.partition_ranking_models import (
    CandidateRankingEntry,
    CandidateSelection,
    SelectionMode,
)
from aiops_k8s_agents.partition_strategies import PartitionIntent


_FORECAST_UNSET = object()


def _positive_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PartitionContractError("invalid_partition_policy", f"{field} must be positive")


def _non_negative_number(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PartitionContractError("invalid_partition_policy", f"{field} must be numeric")
    if not isfinite(float(value)) or float(value) < 0.0:
        raise PartitionContractError(
            "invalid_partition_policy", f"{field} must be non-negative"
        )


def _fraction(value: object, field: str) -> None:
    _non_negative_number(value, field)
    if float(value) > 1.0:
        raise PartitionContractError(
            "invalid_partition_policy", f"{field} must be between 0 and 1"
        )


@dataclass(frozen=True)
class LearnedRankerGuardPolicy:
    minimum_observed_samples: int
    minimum_independent_groups: int
    maximum_holdout_mae: float
    minimum_spearman_correlation: float
    minimum_selection_confidence: float
    maximum_ood_feature_ratio: float

    def __post_init__(self) -> None:
        _positive_integer(self.minimum_observed_samples, "minimum_observed_samples")
        _positive_integer(self.minimum_independent_groups, "minimum_independent_groups")
        _non_negative_number(self.maximum_holdout_mae, "maximum_holdout_mae")
        for value, field in (
            (self.minimum_spearman_correlation, "minimum_spearman_correlation"),
            (self.minimum_selection_confidence, "minimum_selection_confidence"),
            (self.maximum_ood_feature_ratio, "maximum_ood_feature_ratio"),
        ):
            _fraction(value, field)


DEFAULT_LEARNED_RANKER_GUARD_POLICY = LearnedRankerGuardPolicy(
    minimum_observed_samples=30,
    minimum_independent_groups=5,
    maximum_holdout_mae=0.25,
    minimum_spearman_correlation=0.30,
    minimum_selection_confidence=0.70,
    maximum_ood_feature_ratio=0.20,
)


@dataclass(frozen=True)
class RankingContext:
    request: NormalizedPartitionRequest
    intent: PartitionIntent
    strategy_version: str
    workload_forecast: WorkloadForecast | None | object = _FORECAST_UNSET

    def __post_init__(self) -> None:
        normalized_forecast = self.request.workload_forecast
        if self.workload_forecast is _FORECAST_UNSET:
            object.__setattr__(self, "workload_forecast", normalized_forecast)
        elif self.workload_forecast != normalized_forecast:
            raise PartitionContractError(
                "invalid_partition_features",
                "RankingContext workload_forecast must match the normalized request",
            )


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


class LearnedRewardRanker:
    """Pure-Python inference over an already verified JSON model artifact."""

    ranker_id = "learned-reward-ranker"
    ranker_version = "1.0"

    def __init__(self, artifact: PartitionRankerModelArtifact) -> None:
        self.artifact = artifact

    def predict(
        self, features: Mapping[str, float]
    ) -> tuple[float, float, tuple[str, ...]]:
        normalized = self._normalized_features(features)
        reward = self.artifact.intercept + sum(
            coefficient * value
            for coefficient, value in zip(
                self.artifact.coefficients, normalized, strict=True
            )
        )
        if not isfinite(reward):
            raise ValueError("learned reward must be finite")
        confidence, warnings = prediction_confidence(self.artifact, features)
        return max(-1.0, min(1.0, reward)), confidence, warnings

    def feature_contributions(
        self, features: Mapping[str, float]
    ) -> tuple[tuple[str, float], ...]:
        contributions = tuple(
            (name, coefficient * value)
            for name, coefficient, value in zip(
                self.artifact.feature_order,
                self.artifact.coefficients,
                self._normalized_features(features),
                strict=True,
            )
        )
        return tuple(
            sorted(contributions, key=lambda item: (-abs(item[1]), item[0]))[:5]
        )

    def _normalized_features(self, features: Mapping[str, float]) -> tuple[float, ...]:
        return tuple(
            (_finite_feature(features, name) - mean) / scale
            for name, mean, scale in zip(
                self.artifact.feature_order,
                self.artifact.feature_mean,
                self.artifact.feature_scale,
                strict=True,
            )
        )


class GuardedCandidateSelector:
    def __init__(
        self,
        deterministic: CandidateRanker | None = None,
        learned: LearnedRewardRanker | None = None,
        guard_policy: LearnedRankerGuardPolicy = DEFAULT_LEARNED_RANKER_GUARD_POLICY,
    ) -> None:
        self._deterministic = deterministic or DeterministicPolicyRanker()
        self._learned = learned
        self._guard_policy = guard_policy

    def select(
        self,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
        mode: SelectionMode = SelectionMode.DETERMINISTIC,
        model_version: str | None = None,
    ) -> CandidateSelection:
        mode = SelectionMode(mode)
        selection = self._deterministic.rank(context, candidates)
        if mode is SelectionMode.DETERMINISTIC:
            return self._ensure_valid_final(selection, context, candidates)

        availability = self._learned_availability(model_version)
        if availability is not None:
            return self._unavailable_learned_selection(
                selection, context, candidates, mode, availability
            )

        try:
            learned_selection = self._learned_selection(selection, context, candidates)
        except (ArithmeticError, KeyError, TypeError, ValueError, PartitionContractError):
            return self._unavailable_learned_selection(
                selection,
                context,
                candidates,
                mode,
                "learned_inference_error",
            )

        if mode is SelectionMode.SHADOW:
            return self._ensure_valid_final(
                replace(
                    learned_selection,
                    mode=SelectionMode.SHADOW,
                    final_selected_candidate_key=selection.baseline_selected_candidate_key,
                    fallback_used=False,
                    fallback_reason=None,
                    rationale=(
                        "Shadow mode recorded learned ranking without changing the deterministic selection.",
                    ),
                ),
                context,
                candidates,
            )

        try:
            fallback_reason = self._guard_failure(
                learned_selection, context, candidates
            )
        except Exception:
            return self._unavailable_learned_selection(
                selection,
                context,
                candidates,
                mode,
                "learned_inference_error",
            )
        if fallback_reason is not None:
            learned_selection = replace(
                learned_selection,
                final_selected_candidate_key=selection.baseline_selected_candidate_key,
                fallback_used=True,
                fallback_reason=fallback_reason,
                rationale=(
                    "Learned guarded selection fell back to the deterministic baseline.",
                ),
            )
        return self._ensure_valid_final(learned_selection, context, candidates)

    def _learned_availability(self, model_version: str | None) -> str | None:
        if self._learned is None:
            return "model_unavailable"
        artifact = self._learned.artifact
        if model_version is not None and artifact.model_version != model_version:
            return "model_unavailable"
        if (
            artifact.feature_schema_version != FEATURE_SCHEMA_VERSION
            or artifact.feature_order != FEATURE_ORDER
        ):
            return "feature_schema_mismatch"
        try:
            artifact.verify_hash()
        except PartitionContractError:
            return "artifact_hash_invalid"
        return None

    def _learned_selection(
        self,
        baseline: CandidateSelection,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
    ) -> CandidateSelection:
        assert self._learned is not None
        baseline_by_key = {entry.candidate_key: entry for entry in baseline.entries}
        learned_entries: list[CandidateRankingEntry] = []
        invalid_entries: list[CandidateRankingEntry] = []
        for candidate in candidates:
            key = candidate_key(candidate, context.strategy_version)
            baseline_entry = baseline_by_key[key]
            if not candidate.valid:
                invalid_entries.append(baseline_entry)
                continue
            features = extract_partition_features(context, candidate)
            reward, confidence, warnings = self._learned.predict(features)
            learned_entries.append(
                CandidateRankingEntry(
                    candidate_key=key,
                    baseline_score=candidate.score,
                    predicted_reward=reward,
                    prediction_confidence=confidence,
                    rank=0,
                    eligible=True,
                    warnings=tuple(candidate.rejection_reasons) + warnings,
                    feature_contributions=self._learned.feature_contributions(features),
                )
            )
        ordered_learned = sorted(
            learned_entries,
            key=lambda entry: (
                -float(entry.predicted_reward),
                -float(entry.prediction_confidence),
                entry.baseline_score,
                entry.candidate_key,
            ),
        )
        entries = tuple(
            replace(entry, rank=index)
            for index, entry in enumerate(
                (*ordered_learned, *invalid_entries), start=1
            )
        )
        selected = ordered_learned[0] if ordered_learned else None
        return CandidateSelection(
            mode=SelectionMode.LEARNED_GUARDED,
            active_ranker_id=LearnedRewardRanker.ranker_id,
            active_ranker_version=LearnedRewardRanker.ranker_version,
            baseline_selected_candidate_key=baseline.baseline_selected_candidate_key,
            learned_selected_candidate_key=(
                None if selected is None else selected.candidate_key
            ),
            final_selected_candidate_key=(
                None if selected is None else selected.candidate_key
            ),
            model_version=self._learned.artifact.model_version,
            model_artifact_hash=self._learned.artifact.artifact_hash,
            feature_schema_version=self._learned.artifact.feature_schema_version,
            entries=entries,
            confidence=1.0 if selected is None else float(selected.prediction_confidence),
            fallback_used=False,
            fallback_reason=None,
            rationale=("Learned reward ranker ordered feasible candidates.",),
        )

    def _guard_failure(
        self,
        selection: CandidateSelection,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
    ) -> str | None:
        assert self._learned is not None
        artifact = self._learned.artifact
        policy = self._guard_policy
        if artifact.sample_count < policy.minimum_observed_samples:
            return "insufficient_observed_samples"
        if artifact.group_count < policy.minimum_independent_groups:
            return "insufficient_independent_groups"
        holdout_mae = _metric(artifact.validation_metrics, "holdout_mae", "mae")
        if holdout_mae is None or holdout_mae > policy.maximum_holdout_mae:
            return "holdout_mae_exceeded"
        correlation = _metric(
            artifact.validation_metrics,
            "spearman_correlation",
            "spearman_rank_correlation",
        )
        if correlation is None or correlation < policy.minimum_spearman_correlation:
            return "rank_correlation_below_threshold"
        selected = next(
            (
                entry
                for entry in selection.entries
                if entry.candidate_key == selection.learned_selected_candidate_key
            ),
            None,
        )
        if selected is None or not selected.eligible:
            return "learned_inference_error"
        selected_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate_key(candidate, context.strategy_version)
                == selected.candidate_key
            ),
            None,
        )
        if selected_candidate is None or not selected_candidate.valid:
            return "learned_inference_error"
        features_ood_ratio = _ood_feature_ratio(
            artifact,
            extract_partition_features(context, selected_candidate),
        )
        if features_ood_ratio > policy.maximum_ood_feature_ratio:
            return "feature_distribution_shift"
        if (
            selected.prediction_confidence is None
            or selected.prediction_confidence < policy.minimum_selection_confidence
        ):
            return "selection_confidence_below_threshold"
        return None

    def _unavailable_learned_selection(
        self,
        baseline: CandidateSelection,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
        mode: SelectionMode,
        reason: str,
    ) -> CandidateSelection:
        return self._ensure_valid_final(
            replace(
                baseline,
                mode=mode,
                learned_selected_candidate_key=None,
                final_selected_candidate_key=baseline.baseline_selected_candidate_key,
                fallback_used=mode is SelectionMode.LEARNED_GUARDED,
                fallback_reason=(
                    reason if mode is SelectionMode.LEARNED_GUARDED else None
                ),
                rationale=("Deterministic selection is retained because learned ranking is unavailable.",),
            ),
            context,
            candidates,
        )

    @staticmethod
    def _ensure_valid_final(
        selection: CandidateSelection,
        context: RankingContext,
        candidates: Sequence[PartitionCandidate],
    ) -> CandidateSelection:
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


def prediction_confidence(
    artifact: PartitionRankerModelArtifact, features: Mapping[str, float]
) -> tuple[float, tuple[str, ...]]:
    ratio = _ood_feature_ratio(artifact, features)
    base_confidence = artifact.confidence_policy.get("base_confidence", 1.0)
    if not isinstance(base_confidence, (int, float)) or isinstance(base_confidence, bool):
        raise ValueError("base_confidence must be numeric")
    confidence = max(0.0, min(1.0, float(base_confidence) * (1.0 - ratio)))
    warnings = () if ratio == 0.0 else ("feature_distribution_shift",)
    return confidence, warnings


def _ood_feature_ratio(
    artifact: PartitionRankerModelArtifact, features: Mapping[str, float]
) -> float:
    outside = 0
    for name in artifact.feature_order:
        value = _finite_feature(features, name)
        lower, upper = artifact.training_feature_ranges[name]
        if value < lower or value > upper:
            outside += 1
    return outside / len(artifact.feature_order)


def _metric(metrics: Mapping[str, float], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
            if isfinite(numeric):
                return numeric
    return None


def _finite_feature(features: Mapping[str, float], name: str) -> float:
    if name not in features:
        raise ValueError(f"feature {name} is missing")
    value = features[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"feature {name} must be numeric")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"feature {name} must be finite")
    return number


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

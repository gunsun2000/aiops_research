from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from aiops_k8s_agents.mutual_supervision_models import PeerReview, ReviewVerdict
from aiops_k8s_agents.research_protocol import (
    ConsensusStrategy,
    ProtocolAgentBinding,
    ResearchProtocolProfile,
)


@dataclass(frozen=True)
class ConsensusOutcome:
    approved: bool
    strategy: str
    score: float
    blocking_vetoes: tuple[str, ...]
    non_blocking_objections: tuple[str, ...]
    revisions: tuple[PeerReview, ...]
    reason: str


class ConsensusResolver:
    """Resolve review outcomes without changing reviews or executing actions."""

    def resolve(
        self,
        reviews: Iterable[PeerReview],
        profile: ResearchProtocolProfile,
        decision_scope: str | Iterable[str],
    ) -> ConsensusOutcome:
        review_tuple = tuple(reviews)
        bindings = {binding.name: binding for binding in profile.agents}
        ordered_reviews = _order_reviews(review_tuple, bindings)
        bound_reviews = tuple(
            review for review in ordered_reviews if review.reviewer in bindings
        )
        enabled_reviews = tuple(
            review
            for review in bound_reviews
            if _is_enabled_reviewer(review, bindings)
        )
        revisions = tuple(
            review
            for review in review_tuple
            if review.verdict is ReviewVerdict.REVISE
        )

        if profile.consensus_strategy is ConsensusStrategy.ROLE_BASED_VETO:
            return self._resolve_role_based_veto(
                bound_reviews,
                revisions,
                bindings,
                _normalize_decision_scopes(decision_scope),
            )
        if profile.consensus_strategy is ConsensusStrategy.UNANIMOUS_VETO:
            return self._resolve_unanimous_veto(ordered_reviews, revisions)
        if profile.consensus_strategy is ConsensusStrategy.WEIGHTED_MAJORITY:
            return self._resolve_weighted_majority(
                enabled_reviews, revisions, bindings
            )
        raise ValueError(f"unsupported consensus strategy: {profile.consensus_strategy}")

    @staticmethod
    def _resolve_role_based_veto(
        reviews: tuple[PeerReview, ...],
        revisions: tuple[PeerReview, ...],
        bindings: dict[str, ProtocolAgentBinding],
        decision_scopes: tuple[str, ...],
    ) -> ConsensusOutcome:
        blocking = tuple(
            review.reviewer
            for review in reviews
            if review.verdict is ReviewVerdict.VETO
            and any(
                scope in bindings[review.reviewer].veto_scopes
                for scope in decision_scopes
            )
        )
        non_blocking = tuple(
            review.reviewer
            for review in reviews
            if review.verdict is ReviewVerdict.VETO
            and not any(
                scope in bindings[review.reviewer].veto_scopes
                for scope in decision_scopes
            )
        )
        approved = not blocking
        return ConsensusOutcome(
            approved=approved,
            strategy=ConsensusStrategy.ROLE_BASED_VETO.value,
            score=1.0 if approved else 0.0,
            blocking_vetoes=blocking,
            non_blocking_objections=non_blocking,
            revisions=revisions,
            reason=(
                "matching role vetoes: " + ", ".join(blocking)
                if blocking
                else "no matching role vetoes"
            ),
        )

    @staticmethod
    def _resolve_unanimous_veto(
        reviews: tuple[PeerReview, ...],
        revisions: tuple[PeerReview, ...],
    ) -> ConsensusOutcome:
        blocking = tuple(
            review.reviewer
            for review in reviews
            if review.verdict is ReviewVerdict.VETO
        )
        approved = not blocking
        return ConsensusOutcome(
            approved=approved,
            strategy=ConsensusStrategy.UNANIMOUS_VETO.value,
            score=1.0 if approved else 0.0,
            blocking_vetoes=blocking,
            non_blocking_objections=(),
            revisions=revisions,
            reason=(
                "vetoes: " + ", ".join(blocking)
                if blocking
                else "no vetoes"
            ),
        )

    @staticmethod
    def _resolve_weighted_majority(
        reviews: tuple[PeerReview, ...],
        revisions: tuple[PeerReview, ...],
        bindings: dict[str, ProtocolAgentBinding],
    ) -> ConsensusOutcome:
        participating_weight = sum(
            bindings[review.reviewer].consensus_weight for review in reviews
        )
        approve_weight = sum(
            bindings[review.reviewer].consensus_weight
            for review in reviews
            if review.verdict is ReviewVerdict.APPROVE
        )
        score = approve_weight / participating_weight if participating_weight else 0.0
        approved = score >= 0.5
        objections = tuple(
            review.reviewer
            for review in reviews
            if review.verdict is ReviewVerdict.VETO
        )
        return ConsensusOutcome(
            approved=approved,
            strategy=ConsensusStrategy.WEIGHTED_MAJORITY.value,
            score=score,
            blocking_vetoes=(),
            non_blocking_objections=objections,
            revisions=revisions,
            reason=(
                "weighted approval threshold met"
                if approved
                else "weighted approval threshold not met"
            ),
        )


def _is_enabled_reviewer(
    review: PeerReview, bindings: dict[str, ProtocolAgentBinding]
) -> bool:
    binding = bindings.get(review.reviewer)
    return binding is not None and binding.enabled


def _normalize_decision_scopes(
    decision_scope: str | Iterable[str],
) -> tuple[str, ...]:
    if isinstance(decision_scope, str):
        return (decision_scope,)
    return tuple(decision_scope)


def _order_reviews(
    reviews: tuple[PeerReview, ...], bindings: dict[str, ProtocolAgentBinding]
) -> tuple[PeerReview, ...]:
    binding_order = {name: index for index, name in enumerate(bindings)}
    return tuple(
        sorted(
            reviews,
            key=lambda review: (
                binding_order.get(review.reviewer, len(binding_order)),
                review.reviewer,
                review.review_id,
            ),
        )
    )

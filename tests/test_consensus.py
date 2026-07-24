from dataclasses import replace

import pytest

from aiops_k8s_agents.consensus import ConsensusResolver
from aiops_k8s_agents.mutual_supervision_models import PeerReview, ReviewVerdict
from aiops_k8s_agents.research_protocol import load_research_protocol


def review(reviewer: str, verdict: ReviewVerdict) -> PeerReview:
    return PeerReview(
        review_id=f"review-{reviewer}",
        run_id="run-1",
        round_index=1,
        reviewer=reviewer,
        target_agent="AIApplicationManagementAgent",
        target_decision_id="decision-1",
        verdict=verdict,
        reason=f"{reviewer} review",
        suggested_action=None,
        confidence=0.9,
        evidence_refs=(),
        policy_version="protocol-v1",
    )


@pytest.fixture
def resolver() -> ConsensusResolver:
    return ConsensusResolver()


@pytest.fixture
def role_profile():
    return load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )


@pytest.fixture
def unanimous_profile():
    return load_research_protocol(
        "config/protocol_profiles/four-agent-unanimous-v1.json"
    )


@pytest.fixture
def weighted_profile():
    return load_research_protocol(
        "config/protocol_profiles/four-agent-weighted-v1.json"
    )


def test_role_veto_blocks_only_reviewers_with_matching_scope(resolver, role_profile):
    outcome = resolver.resolve(
        reviews=(
            review("CostOptimizationAgent", ReviewVerdict.VETO),
            review("AISemiconductorInfraOpsAgent", ReviewVerdict.APPROVE),
        ),
        profile=role_profile,
        decision_scope="capacity",
    )

    assert outcome.approved
    assert outcome.blocking_vetoes == ()
    assert outcome.non_blocking_objections == ("CostOptimizationAgent",)


def test_role_veto_blocks_matching_reviewer_scope(resolver, role_profile):
    outcome = resolver.resolve(
        reviews=(review("AISemiconductorInfraOpsAgent", ReviewVerdict.VETO),),
        profile=role_profile,
        decision_scope="capacity",
    )

    assert not outcome.approved
    assert outcome.blocking_vetoes == ("AISemiconductorInfraOpsAgent",)


def test_role_veto_blocks_reviewers_matching_any_decision_scope(
    resolver, role_profile
):
    outcome = resolver.resolve(
        reviews=(
            review("AISemiconductorInfraOpsAgent", ReviewVerdict.VETO),
            review("CostOptimizationAgent", ReviewVerdict.VETO),
        ),
        profile=role_profile,
        decision_scope=("capacity", "budget"),
    )

    assert not outcome.approved
    assert outcome.blocking_vetoes == (
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    )
    assert outcome.non_blocking_objections == ()


def test_unanimous_veto_blocks_on_any_veto(resolver, unanimous_profile):
    outcome = resolver.resolve(
        reviews=(review("CostOptimizationAgent", ReviewVerdict.VETO),),
        profile=unanimous_profile,
        decision_scope="capacity",
    )

    assert not outcome.approved
    assert outcome.blocking_vetoes == ("CostOptimizationAgent",)


def test_unanimous_veto_blocks_a_veto_from_a_disabled_binding(
    resolver, unanimous_profile
):
    disabled_cost = replace(
        next(
            binding
            for binding in unanimous_profile.agents
            if binding.name == "CostOptimizationAgent"
        ),
        enabled=False,
    )
    profile = replace(
        unanimous_profile,
        agents=tuple(
            disabled_cost if binding.name == disabled_cost.name else binding
            for binding in unanimous_profile.agents
        ),
    )

    outcome = resolver.resolve(
        reviews=(review("CostOptimizationAgent", ReviewVerdict.VETO),),
        profile=profile,
        decision_scope="capacity",
    )

    assert not outcome.approved
    assert outcome.blocking_vetoes == ("CostOptimizationAgent",)


def test_weighted_majority_uses_enabled_participating_agent_weights(
    resolver, weighted_profile
):
    weight_by_name = {
        "AIServiceHASupportAgent": 0.5,
        "AIApplicationManagementAgent": 0.25,
        "AISemiconductorInfraOpsAgent": 0.25,
        "CostOptimizationAgent": 1.0,
    }
    disabled_cost = replace(
        next(
            binding
            for binding in weighted_profile.agents
            if binding.name == "CostOptimizationAgent"
        ),
        enabled=False,
        consensus_weight=weight_by_name["CostOptimizationAgent"],
    )
    profile = replace(
        weighted_profile,
        agents=tuple(
            (
                disabled_cost
                if binding.name == disabled_cost.name
                else replace(
                    binding, consensus_weight=weight_by_name[binding.name]
                )
            )
            for binding in weighted_profile.agents
        ),
    )

    outcome = resolver.resolve(
        reviews=(
            review("AIServiceHASupportAgent", ReviewVerdict.APPROVE),
            review("AISemiconductorInfraOpsAgent", ReviewVerdict.APPROVE),
            review("AIApplicationManagementAgent", ReviewVerdict.VETO),
            review("CostOptimizationAgent", ReviewVerdict.APPROVE),
        ),
        profile=profile,
        decision_scope="capacity",
    )

    assert outcome.score == pytest.approx(0.75)
    assert outcome.approved


def test_weighted_majority_objections_follow_profile_agent_order(
    resolver, weighted_profile
):
    outcome = resolver.resolve(
        reviews=(
            review("CostOptimizationAgent", ReviewVerdict.VETO),
            review("AIServiceHASupportAgent", ReviewVerdict.VETO),
        ),
        profile=weighted_profile,
        decision_scope="capacity",
    )

    assert outcome.non_blocking_objections == (
        "AIServiceHASupportAgent",
        "CostOptimizationAgent",
    )


def test_weighted_majority_counts_abstaining_weight_without_approving_weight(
    resolver, weighted_profile
):
    outcome = resolver.resolve(
        reviews=(
            review("AIServiceHASupportAgent", ReviewVerdict.APPROVE),
            review("CostOptimizationAgent", ReviewVerdict.ABSTAIN),
        ),
        profile=weighted_profile,
        decision_scope="capacity",
    )

    assert outcome.score == pytest.approx(0.8)
    assert outcome.approved


def test_resolver_preserves_revisions_without_mutating_reviews(resolver, role_profile):
    reviews = (review("CostOptimizationAgent", ReviewVerdict.REVISE),)

    first = resolver.resolve(reviews, role_profile, "capacity")
    second = resolver.resolve(reviews, role_profile, "capacity")

    assert first.revisions == reviews
    assert first == second
    assert reviews[0].verdict is ReviewVerdict.REVISE

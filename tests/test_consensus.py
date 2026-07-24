from dataclasses import replace

import pytest

from aiops_k8s_agents.consensus import ConsensusResolver
from aiops_k8s_agents.agent_adapters import (
    ReviewContext,
    build_default_agent_adapter_registry,
)
from aiops_k8s_agents.evidence import EvidenceSnapshot
from aiops_k8s_agents.models import RecoveryAction, RecoveryActionKind
from aiops_k8s_agents.mutual_supervision import _decision_scopes
from aiops_k8s_agents.mutual_supervision_models import (
    PeerReview,
    ReviewVerdict,
    SupervisionDecision,
)
from aiops_k8s_agents.research_protocol import (
    ResearchProtocolProfile,
    load_research_protocol,
)


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


def test_unanimous_veto_excludes_a_veto_from_a_disabled_binding(
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
    profile = profile_with_binding(unanimous_profile, disabled_cost)

    outcome = resolver.resolve(
        reviews=(review("CostOptimizationAgent", ReviewVerdict.VETO),),
        profile=profile,
        decision_scope="capacity",
    )

    assert outcome.approved
    assert outcome.blocking_vetoes == ()


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
    source = weighted_profile.to_canonical_dict()
    source.pop("config_hash")
    for binding in source["agents"]:
        binding["consensus_weight"] = weight_by_name[binding["name"]]
        if binding["name"] == disabled_cost.name:
            binding["enabled"] = False
    profile = ResearchProtocolProfile.from_dict(source)

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


def test_role_veto_excludes_disabled_and_unbound_reviews_and_revisions(
    resolver,
    role_profile,
):
    disabled_cost = replace(
        next(
            binding
            for binding in role_profile.agents
            if binding.name == "CostOptimizationAgent"
        ),
        enabled=False,
    )
    profile = profile_with_binding(role_profile, disabled_cost)

    outcome = resolver.resolve(
        reviews=(
            review("CostOptimizationAgent", ReviewVerdict.VETO),
            review("UnboundReviewer", ReviewVerdict.REVISE),
        ),
        profile=profile,
        decision_scope=("budget", "action_validity"),
    )

    assert outcome.approved
    assert outcome.blocking_vetoes == ()
    assert outcome.non_blocking_objections == ()
    assert outcome.revisions == ()


@pytest.mark.parametrize(
    ("profile_fixture", "expected_approved"),
    [
        ("role_profile", True),
        ("unanimous_profile", True),
        ("weighted_profile", False),
    ],
)
def test_all_strategies_exclude_unbound_reviewers(
    request,
    resolver,
    profile_fixture,
    expected_approved,
):
    profile = request.getfixturevalue(profile_fixture)

    outcome = resolver.resolve(
        reviews=(review("UnboundReviewer", ReviewVerdict.VETO),),
        profile=profile,
        decision_scope="action_validity",
    )

    assert outcome.approved is expected_approved
    assert outcome.blocking_vetoes == ()
    assert outcome.non_blocking_objections == ()
    assert outcome.revisions == ()


@pytest.mark.parametrize(
    ("kind", "required_scopes"),
    [
        (
            RecoveryActionKind.OBSERVE_ONLY,
            {"action_validity", "target_alignment", "availability"},
        ),
        (
            RecoveryActionKind.ROLLOUT_RESTART,
            {
                "action_validity",
                "target_alignment",
                "availability",
                "recovery",
                "executability",
            },
        ),
        (
            RecoveryActionKind.SCALE_OUT,
            {
                "action_validity",
                "target_alignment",
                "capacity",
                "resource_safety",
                "budget",
            },
        ),
    ],
)
def test_application_target_mismatch_veto_blocks_every_bounded_action(
    resolver,
    role_profile,
    kind,
    required_scopes,
):
    adapters = {
        adapter.name: adapter
        for adapter in build_default_agent_adapter_registry().create_profile(
            role_profile
        )
    }
    application = adapters["AIApplicationManagementAgent"]
    action = RecoveryAction(
        namespace="wrong-namespace",
        deployment="wrong-deployment",
        kind=kind,
        replicas=2 if kind is RecoveryActionKind.SCALE_OUT else None,
        reason="mismatched target",
    )
    decision = SupervisionDecision(
        decision_id="decision-mismatch",
        run_id="run-mismatch",
        round_index=1,
        agent="AIServiceHASupportAgent",
        decision_type="recovery_action_proposal",
        proposed_action=action,
        approved=True,
        reason=action.reason,
        confidence=0.9,
        evidence_refs=(),
        reward=0.0,
        policy_version=role_profile.version,
    )
    evidence = EvidenceSnapshot(
        namespace="online-boutique",
        deployment="paymentservice",
        metric_values={"cpu": 95.0},
    )
    mismatch_review = application.review(
        decision,
        evidence,
        ReviewContext(
            run_id=decision.run_id,
            round_index=decision.round_index,
            policy_version=role_profile.version,
        ),
    )
    scopes = _decision_scopes(action)

    assert required_scopes.issubset(scopes)
    assert mismatch_review is not None
    assert mismatch_review.verdict is ReviewVerdict.VETO
    outcome = resolver.resolve((mismatch_review,), role_profile, scopes)
    assert not outcome.approved
    assert outcome.blocking_vetoes == ("AIApplicationManagementAgent",)


def profile_with_binding(profile, replacement):
    source = profile.to_canonical_dict()
    source.pop("config_hash")
    for index, binding in enumerate(source["agents"]):
        if binding["name"] == replacement.name:
            source["agents"][index] = {
                "name": replacement.name,
                "implementation_id": replacement.implementation_id,
                "runtime": replacement.runtime,
                "enabled": replacement.enabled,
                "veto_scopes": list(replacement.veto_scopes),
                "consensus_weight": replacement.consensus_weight,
                "capabilities": list(replacement.capabilities),
            }
            break
    return ResearchProtocolProfile.from_dict(source)

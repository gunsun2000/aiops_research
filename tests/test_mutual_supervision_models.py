from aiops_k8s_agents.models import RecoveryAction, RecoveryActionKind
from aiops_k8s_agents.mutual_supervision_models import (
    NegotiationRound,
    PeerReview,
    ReviewVerdict,
    SupervisionDecision,
    new_trace_id,
    to_serializable,
)


def test_peer_review_serializes_traceable_structured_revision():
    action = RecoveryAction(
        namespace="online-boutique",
        deployment="paymentservice",
        kind=RecoveryActionKind.SCALE_OUT,
        replicas=2,
        reason="cost-bounded revision",
    )
    review = PeerReview(
        review_id="review-1",
        run_id="run-1",
        round_index=1,
        reviewer="CostOptimizationAgent",
        target_agent="AIApplicationManagementAgent",
        target_decision_id="decision-1",
        verdict=ReviewVerdict.REVISE,
        reason="replica 3 exceeds cost policy",
        suggested_action=action,
        confidence=0.91,
        evidence_refs=("current_replicas", "cost_policy"),
        policy_version="mutual-v1",
    )

    payload = to_serializable(review)

    assert payload["verdict"] == "revise"
    assert payload["suggested_action"]["kind"] == "scale_out"
    assert payload["suggested_action"]["replicas"] == 2
    assert payload["evidence_refs"] == ["current_replicas", "cost_policy"]


def test_negotiation_round_serializes_decision_and_review_identifiers():
    negotiation = NegotiationRound(
        run_id="run-1",
        round_index=2,
        input_decision_ids=("decision-1",),
        review_ids=("review-1", "review-2"),
        revisions=("replicas:3->2",),
        remaining_vetoes=(),
        remaining_abstentions=(),
        consensus_status="approved",
        selected_action_id="action-2",
        decision_scopes=("capacity", "budget"),
        consensus_strategy="role_based_veto",
        non_blocking_objections=("CostOptimizationAgent",),
        consensus_reason="no matching role vetoes",
    )

    payload = to_serializable(negotiation)

    assert payload["round_index"] == 2
    assert payload["review_ids"] == ["review-1", "review-2"]
    assert payload["selected_action_id"] == "action-2"
    assert payload["decision_scopes"] == ["capacity", "budget"]
    assert payload["consensus_strategy"] == "role_based_veto"


def test_supervision_decision_and_trace_ids_are_json_ready_and_unique():
    decision = SupervisionDecision(
        decision_id="decision-1",
        run_id="run-1",
        round_index=1,
        agent="AIApplicationManagementAgent",
        decision_type="recovery_action_proposal",
        proposed_action=None,
        approved=True,
        reason="observe first",
        confidence=0.75,
        evidence_refs=("metric:cpu",),
        reward=0.4,
        policy_version="mutual-v1",
    )

    first = new_trace_id("review")
    second = new_trace_id("review")

    assert first.startswith("review-")
    assert second.startswith("review-")
    assert first != second
    assert to_serializable(decision)["evidence_refs"] == ["metric:cpu"]

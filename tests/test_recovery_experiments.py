import pytest

from aiops_k8s_agents.models import RecoveryAction, RecoveryActionKind
from aiops_k8s_agents.recovery_experiments import (
    RECOVERY_REWARD_POLICIES,
    RecoveryOutcome,
    RewardWeights,
    rank_recovery_actions,
)


def test_reward_weights_must_be_non_negative_and_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        RewardWeights(ha=0.4, application=0.3, infrastructure=0.2, cost=0.2)

    with pytest.raises(ValueError, match="non-negative"):
        RewardWeights(ha=0.6, application=0.3, infrastructure=0.2, cost=-0.1)


def test_reward_policy_can_change_selected_action_for_same_real_outcomes():
    scale = RecoveryOutcome(
        scenario="cpu-stress",
        action=RecoveryAction(
            namespace="online-boutique",
            deployment="paymentservice",
            kind=RecoveryActionKind.SCALE_OUT,
            replicas=3,
            reason="candidate treatment",
        ),
        recovery_success=True,
        availability_recovery=1.0,
        metric_improvement=0.95,
        recovery_seconds=10.0,
        replica_delta=2,
        command_count=1,
        safety_valid=True,
        measurement_valid=True,
    )
    observe = RecoveryOutcome(
        scenario="cpu-stress",
        action=RecoveryAction(
            namespace="online-boutique",
            deployment="paymentservice",
            kind=RecoveryActionKind.OBSERVE_ONLY,
            reason="candidate treatment",
        ),
        recovery_success=True,
        availability_recovery=0.8,
        metric_improvement=0.6,
        recovery_seconds=50.0,
        replica_delta=0,
        command_count=0,
        safety_valid=True,
        measurement_valid=True,
    )

    ha_ranking = rank_recovery_actions(
        [scale, observe], RECOVERY_REWARD_POLICIES["ha_first"]
    )
    cost_ranking = rank_recovery_actions(
        [scale, observe], RECOVERY_REWARD_POLICIES["cost_first"]
    )

    assert ha_ranking[0].outcome.action.kind == RecoveryActionKind.SCALE_OUT
    assert cost_ranking[0].outcome.action.kind == RecoveryActionKind.OBSERVE_ONLY
    assert ha_ranking[0].predicted_reward != cost_ranking[0].predicted_reward


def test_invalid_measurement_is_never_selected_over_valid_measurement():
    invalid = RecoveryOutcome(
        scenario="network-delay",
        action=RecoveryAction(
            namespace="online-boutique",
            deployment="paymentservice",
            kind=RecoveryActionKind.ROLLOUT_RESTART,
            reason="latency query was invalid",
        ),
        recovery_success=True,
        availability_recovery=1.0,
        metric_improvement=1.0,
        recovery_seconds=1.0,
        replica_delta=0,
        command_count=1,
        safety_valid=True,
        measurement_valid=False,
    )
    valid = RecoveryOutcome(
        scenario="network-delay",
        action=RecoveryAction(
            namespace="online-boutique",
            deployment="paymentservice",
            kind=RecoveryActionKind.OBSERVE_ONLY,
            reason="valid active probe",
        ),
        recovery_success=False,
        availability_recovery=0.5,
        metric_improvement=0.1,
        recovery_seconds=60.0,
        replica_delta=0,
        command_count=0,
        safety_valid=True,
        measurement_valid=True,
    )

    ranking = rank_recovery_actions(
        [invalid, valid], RECOVERY_REWARD_POLICIES["balanced"]
    )

    assert ranking[0].outcome.action.kind == RecoveryActionKind.OBSERVE_ONLY
    assert ranking[-1].predicted_reward < 0

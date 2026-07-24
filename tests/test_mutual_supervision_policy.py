import json

import pytest

from aiops_k8s_agents.mutual_supervision_policy import (
    load_mutual_supervision_policy,
)


def test_default_policy_requires_three_reviews_for_application_action():
    policy = load_mutual_supervision_policy(
        "config/mutual_supervision_policy.json"
    )

    assert policy.version == "mutual-supervision-v1"
    assert policy.max_negotiation_rounds == 2
    assert policy.max_replan_attempts == 1
    assert policy.reviewers_for("AIApplicationManagementAgent") == (
        "AIServiceHASupportAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_negotiation_rounds": 0}, "max_negotiation_rounds"),
        ({"max_replan_attempts": -1}, "max_replan_attempts"),
        ({"fallback_action": "delete_namespace"}, "fallback_action"),
    ],
)
def test_policy_rejects_unsafe_protocol_values(tmp_path, overrides, message):
    payload = _valid_policy()
    payload.update(overrides)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_mutual_supervision_policy(path)


def test_policy_rejects_unknown_review_participant(tmp_path):
    payload = _valid_policy()
    payload["review_matrix"]["AIApplicationManagementAgent"].append(
        "UnknownAgent"
    )
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="UnknownAgent"):
        load_mutual_supervision_policy(path)


def _valid_policy() -> dict:
    return {
        "version": "test-v1",
        "max_negotiation_rounds": 2,
        "max_replan_attempts": 1,
        "fallback_action": "observe_only",
        "review_matrix": {
            "AIServiceHASupportAgent": [
                "AIApplicationManagementAgent",
                "AISemiconductorInfraOpsAgent",
            ],
            "AIApplicationManagementAgent": [
                "AIServiceHASupportAgent",
                "AISemiconductorInfraOpsAgent",
                "CostOptimizationAgent",
            ],
            "AISemiconductorInfraOpsAgent": [
                "AIApplicationManagementAgent",
                "CostOptimizationAgent",
            ],
            "CostOptimizationAgent": [
                "AIApplicationManagementAgent",
                "AISemiconductorInfraOpsAgent",
            ],
        },
    }

import json
from pathlib import Path

import pytest

from aiops_k8s_agents.models import RecoveryActionKind
from aiops_k8s_agents.research_protocol import (
    ConsensusStrategy,
    ResearchProtocolProfile,
    load_protocol_profiles,
    load_research_protocol,
)


def test_role_veto_profile_has_stable_hash():
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )

    assert profile.profile_id == "four-agent-role-veto-v1"
    assert profile.consensus_strategy is ConsensusStrategy.ROLE_BASED_VETO
    assert profile.max_negotiation_rounds == 2
    assert len(profile.config_hash) == 64


def test_profile_hash_changes_when_consensus_changes():
    source = json.loads(
        Path("config/protocol_profiles/four-agent-role-veto-v1.json").read_text(
            encoding="utf-8"
        )
    )

    first = ResearchProtocolProfile.from_dict(source)
    source["consensus_strategy"] = "unanimous_veto"
    second = ResearchProtocolProfile.from_dict(source)

    assert first.config_hash != second.config_hash


def test_profile_loader_returns_all_profiles_with_enabled_agents():
    profiles = load_protocol_profiles("config/protocol_profiles")

    assert set(profiles) == {
        "four-agent-role-veto-v1",
        "four-agent-unanimous-v1",
        "four-agent-weighted-v1",
    }
    assert all(len(profile.enabled_agents) == 4 for profile in profiles.values())
    assert all(
        binding.runtime == "deterministic"
        for profile in profiles.values()
        for binding in profile.enabled_agents
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"agents": []}, "at least one agent"),
        ({"consensus_strategy": "unknown"}, "consensus_strategy"),
        ({"max_negotiation_rounds": 0}, "max_negotiation_rounds"),
        ({"max_replan_attempts": -1}, "max_replan_attempts"),
        ({"action_space": []}, "action_space"),
        ({"reward_weights": {"safety": -0.1}}, "reward_weights"),
    ],
)
def test_profile_rejects_unsafe_values(tmp_path, overrides, message):
    source = json.loads(
        Path("config/protocol_profiles/four-agent-role-veto-v1.json").read_text(
            encoding="utf-8"
        )
    )
    source.update(overrides)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_research_protocol(path)


def test_profile_rejects_duplicate_agents_and_self_review(tmp_path):
    source = json.loads(
        Path("config/protocol_profiles/four-agent-role-veto-v1.json").read_text(
            encoding="utf-8"
        )
    )
    source["agents"].append(dict(source["agents"][0]))
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate agent"):
        load_research_protocol(path)

    source["agents"].pop()
    source["review_matrix"]["AIServiceHASupportAgent"].append(
        "AIServiceHASupportAgent"
    )
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match="self-review"):
        load_research_protocol(path)


def test_profile_exposes_bounded_actions_and_role_matrix():
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )

    assert profile.fallback_action is RecoveryActionKind.OBSERVE_ONLY
    assert profile.action_space == (
        RecoveryActionKind.OBSERVE_ONLY,
        RecoveryActionKind.ROLLOUT_RESTART,
        RecoveryActionKind.SCALE_OUT,
    )
    assert profile.review_matrix["AIApplicationManagementAgent"] == (
        "AIServiceHASupportAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    )

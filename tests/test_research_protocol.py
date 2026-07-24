import json
from dataclasses import replace
from pathlib import Path

import pytest

from aiops_k8s_agents.models import RecoveryActionKind
from aiops_k8s_agents.research_protocol import (
    ConsensusStrategy,
    DEFAULT_PROTOCOL_PROFILE_ID,
    ResearchProtocolProfile,
    load_protocol_profiles,
    load_research_protocol,
    select_default_protocol_profile,
)


def test_role_veto_profile_has_stable_hash():
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )

    assert profile.profile_id == "four-agent-role-veto-v1"
    assert profile.consensus_strategy is ConsensusStrategy.ROLE_BASED_VETO
    assert profile.max_negotiation_rounds == 2
    assert profile.fallback_action is RecoveryActionKind.OBSERVE_ONLY
    assert profile.human_review_on_failure is True
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


def test_canonical_profile_snapshot_round_trips_with_stable_hash():
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )

    snapshot = profile.to_canonical_dict()
    restored = ResearchProtocolProfile.from_dict(snapshot)

    assert restored == profile
    assert restored.config_hash == profile.config_hash
    assert restored.recomputed_config_hash() == profile.config_hash
    restored.validate_integrity()


def test_stale_dataclass_replacement_fails_integrity_validation():
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    stale = replace(
        profile,
        max_negotiation_rounds=profile.max_negotiation_rounds + 1,
    )

    with pytest.raises(ValueError, match="config_hash"):
        stale.validate_integrity()


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
    assert all(
        profile.fallback_action is RecoveryActionKind.OBSERVE_ONLY
        and profile.human_review_on_failure is True
        for profile in profiles.values()
    )


def test_default_profile_contract_selects_role_veto_profile():
    profiles = load_protocol_profiles("config/protocol_profiles")

    assert DEFAULT_PROTOCOL_PROFILE_ID == "four-agent-role-veto-v1"
    assert (
        select_default_protocol_profile(profiles).profile_id
        == DEFAULT_PROTOCOL_PROFILE_ID
    )


def test_default_profile_selection_rejects_missing_default():
    profiles = load_protocol_profiles("config/protocol_profiles")
    profiles.pop(DEFAULT_PROTOCOL_PROFILE_ID)

    with pytest.raises(ValueError, match=DEFAULT_PROTOCOL_PROFILE_ID):
        select_default_protocol_profile(profiles)


@pytest.mark.parametrize(
    ("field", "value"),
    [("max_negotiation_rounds", 3), ("max_replan_attempts", 0)],
)
def test_default_profile_selection_rejects_mutated_round_limits(field, value):
    profiles = load_protocol_profiles("config/protocol_profiles")
    profiles[DEFAULT_PROTOCOL_PROFILE_ID] = replace(
        profiles[DEFAULT_PROTOCOL_PROFILE_ID], **{field: value}
    )

    with pytest.raises(ValueError, match=field):
        select_default_protocol_profile(profiles)


def test_default_profile_selection_rejects_stale_profile_hash():
    profiles = load_protocol_profiles("config/protocol_profiles")
    profile = profiles[DEFAULT_PROTOCOL_PROFILE_ID]
    profiles[DEFAULT_PROTOCOL_PROFILE_ID] = replace(
        profile,
        experiment_tags=(*profile.experiment_tags, "stale"),
    )

    with pytest.raises(ValueError, match="config_hash"):
        select_default_protocol_profile(profiles)


def test_non_default_profile_selection_remains_configurable():
    profiles = load_protocol_profiles("config/protocol_profiles")
    non_default_id = "four-agent-unanimous-v1"
    profiles[non_default_id] = replace(
        profiles[non_default_id], max_negotiation_rounds=3, max_replan_attempts=0
    )

    selected = select_default_protocol_profile(profiles)

    assert selected.profile_id == DEFAULT_PROTOCOL_PROFILE_ID
    assert profiles[non_default_id].max_negotiation_rounds == 3
    assert profiles[non_default_id].max_replan_attempts == 0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"agents": []}, "at least one agent"),
        ({"consensus_strategy": "unknown"}, "consensus_strategy"),
        ({"max_negotiation_rounds": 0}, "max_negotiation_rounds"),
        ({"max_replan_attempts": -1}, "max_replan_attempts"),
        ({"action_space": []}, "action_space"),
        ({"reward_weights": {"safety": -0.1}}, "reward_weights"),
        ({"fallback_action": "scale_out"}, "fallback_action must be observe_only"),
        ({"human_review_on_failure": False}, "human_review_on_failure"),
        ({"human_review_on_failure": "true"}, "human_review_on_failure"),
        ({"human_review_on_failure": None}, "human_review_on_failure"),
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


def test_profile_requires_explicit_human_review_on_failure_field(tmp_path):
    source = json.loads(
        Path("config/protocol_profiles/four-agent-role-veto-v1.json").read_text(
            encoding="utf-8"
        )
    )
    source.pop("human_review_on_failure")
    path = tmp_path / "missing-human-review.json"
    path.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(ValueError, match="human_review_on_failure"):
        load_research_protocol(path)


def test_profile_accepts_experimental_round_and_replan_limits():
    source = json.loads(
        Path("config/protocol_profiles/four-agent-role-veto-v1.json").read_text(
            encoding="utf-8"
        )
    )
    source["max_negotiation_rounds"] = 3
    source["max_replan_attempts"] = 0

    profile = ResearchProtocolProfile.from_dict(source)

    assert profile.max_negotiation_rounds == 3
    assert profile.max_replan_attempts == 0


def test_profile_loader_rejects_missing_and_empty_directories(tmp_path):
    missing = tmp_path / "missing"
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ValueError, match="does not exist"):
        load_protocol_profiles(missing)
    with pytest.raises(ValueError, match="no JSON profiles"):
        load_protocol_profiles(empty)

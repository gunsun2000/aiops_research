from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from aiops_k8s_agents.models import RecoveryActionKind


DEFAULT_PROTOCOL_PROFILE_ID = "four-agent-role-veto-v1"


class ConsensusStrategy(str, Enum):
    ROLE_BASED_VETO = "role_based_veto"
    UNANIMOUS_VETO = "unanimous_veto"
    WEIGHTED_MAJORITY = "weighted_majority"


_BINDING_KEYS = frozenset(
    {
        "name",
        "implementation_id",
        "runtime",
        "enabled",
        "veto_scopes",
        "consensus_weight",
    }
)
_PROFILE_KEYS = frozenset(
    {
        "profile_id",
        "version",
        "agents",
        "review_matrix",
        "consensus_strategy",
        "max_negotiation_rounds",
        "max_replan_attempts",
        "fallback_action",
        "human_review_on_failure",
        "action_space",
        "reward_weights",
        "experiment_tags",
        "config_hash",
    }
)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_text(data: Mapping[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value.strip()


def _required_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    return value


def _weight(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{label} must not be negative")
    return normalized


def _round_count(value: Any, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class ProtocolAgentBinding:
    name: str
    implementation_id: str
    runtime: str
    enabled: bool
    veto_scopes: tuple[str, ...]
    consensus_weight: float

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProtocolAgentBinding:
        source = _require_mapping(data, "agent binding")
        unknown = set(source) - _BINDING_KEYS
        if unknown:
            raise ValueError(
                "agent binding contains unknown fields: "
                + ", ".join(sorted(unknown))
            )

        raw_scopes = _required_list(source.get("veto_scopes"), "veto_scopes")
        scopes = tuple(_required_text({"value": item}, "value", "veto scope") for item in raw_scopes)
        if len(set(scopes)) != len(scopes):
            raise ValueError("veto_scopes must not contain duplicates")
        enabled = source.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")

        return cls(
            name=_required_text(source, "name", "agent name"),
            implementation_id=_required_text(
                source, "implementation_id", "implementation_id"
            ),
            runtime=_required_text(source, "runtime", "runtime"),
            enabled=enabled,
            veto_scopes=scopes,
            consensus_weight=_weight(
                source.get("consensus_weight"), "consensus_weight"
            ),
        )


@dataclass(frozen=True)
class ResearchProtocolProfile:
    profile_id: str
    version: str
    agents: tuple[ProtocolAgentBinding, ...]
    review_matrix: Mapping[str, tuple[str, ...]]
    consensus_strategy: ConsensusStrategy
    max_negotiation_rounds: int
    max_replan_attempts: int
    fallback_action: RecoveryActionKind
    human_review_on_failure: bool
    action_space: tuple[RecoveryActionKind, ...]
    reward_weights: Mapping[str, float]
    experiment_tags: tuple[str, ...]
    config_hash: str

    @property
    def enabled_agents(self) -> tuple[ProtocolAgentBinding, ...]:
        return tuple(binding for binding in self.agents if binding.enabled)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ResearchProtocolProfile:
        source = _require_mapping(data, "protocol profile")
        unknown = set(source) - _PROFILE_KEYS
        if unknown:
            raise ValueError(
                "protocol profile contains unknown fields: "
                + ", ".join(sorted(unknown))
            )

        raw_agents = source.get("agents")
        if not isinstance(raw_agents, list) or not raw_agents:
            raise ValueError("profile must contain at least one agent")
        agents = tuple(ProtocolAgentBinding.from_dict(item) for item in raw_agents)
        agent_names = tuple(binding.name for binding in agents)
        if len(set(agent_names)) != len(agent_names):
            raise ValueError("duplicate agent name in profile")

        matrix_source = _require_mapping(
            source.get("review_matrix"), "review_matrix"
        )
        if set(matrix_source) != set(agent_names):
            missing = sorted(set(agent_names) - set(matrix_source))
            unknown_targets = sorted(set(matrix_source) - set(agent_names))
            details = []
            if missing:
                details.append("missing targets: " + ", ".join(missing))
            if unknown_targets:
                details.append("unknown targets: " + ", ".join(unknown_targets))
            raise ValueError("review_matrix does not match agents (" + "; ".join(details) + ")")

        matrix: dict[str, tuple[str, ...]] = {}
        for target, raw_reviewers in matrix_source.items():
            if not isinstance(target, str) or not target.strip():
                raise ValueError("review_matrix targets must be non-empty strings")
            reviewers = _required_list(raw_reviewers, f"reviewers for {target}")
            normalized_reviewers = tuple(
                _required_text({"value": reviewer}, "value", "reviewer")
                for reviewer in reviewers
            )
            unknown_reviewers = set(normalized_reviewers) - set(agent_names)
            if unknown_reviewers:
                raise ValueError(
                    "unknown review participant: "
                    + ", ".join(sorted(unknown_reviewers))
                )
            if target in normalized_reviewers:
                raise ValueError(f"agent cannot self-review: {target}")
            if len(set(normalized_reviewers)) != len(normalized_reviewers):
                raise ValueError(f"reviewers for {target} must not contain duplicates")
            matrix[target] = normalized_reviewers

        try:
            consensus_strategy = ConsensusStrategy(
                _required_text(source, "consensus_strategy", "consensus_strategy")
            )
        except ValueError as exc:
            raise ValueError(
                "unknown consensus_strategy: "
                + str(source.get("consensus_strategy", ""))
            ) from exc

        fallback_raw = _required_text(source, "fallback_action", "fallback_action")
        try:
            fallback_action = RecoveryActionKind(fallback_raw)
        except ValueError as exc:
            raise ValueError(f"unknown fallback_action: {fallback_raw}") from exc
        if fallback_action is not RecoveryActionKind.OBSERVE_ONLY:
            raise ValueError("fallback_action must be observe_only")

        human_review_on_failure = source.get("human_review_on_failure")
        if human_review_on_failure is not True:
            raise ValueError("human_review_on_failure must be true")

        raw_actions = _required_list(source.get("action_space"), "action_space")
        try:
            action_space = tuple(RecoveryActionKind(str(item)) for item in raw_actions)
        except ValueError as exc:
            raise ValueError("action_space contains an unknown recovery action") from exc
        if len(set(action_space)) != len(action_space):
            raise ValueError("action_space must not contain duplicates")
        if fallback_action not in action_space:
            raise ValueError("fallback_action must be included in action_space")

        reward_source = _require_mapping(
            source.get("reward_weights"), "reward_weights"
        )
        if not reward_source:
            raise ValueError("reward_weights must be a non-empty object")
        reward_weights = {
            _required_text({"value": key}, "value", "reward weight name"): _weight(
                value, f"reward_weights[{key}]"
            )
            for key, value in reward_source.items()
        }

        raw_tags = _required_list(source.get("experiment_tags"), "experiment_tags")
        experiment_tags = tuple(
            _required_text({"value": tag}, "value", "experiment tag")
            for tag in raw_tags
        )
        if len(set(experiment_tags)) != len(experiment_tags):
            raise ValueError("experiment_tags must not contain duplicates")

        config_hash = _config_hash(source)
        supplied_hash = source.get("config_hash")
        if supplied_hash is not None:
            if not isinstance(supplied_hash, str) or supplied_hash != config_hash:
                raise ValueError("config_hash does not match profile contents")

        return cls(
            profile_id=_required_text(source, "profile_id", "profile_id"),
            version=_required_text(source, "version", "version"),
            agents=agents,
            review_matrix=MappingProxyType(matrix),
            consensus_strategy=consensus_strategy,
            max_negotiation_rounds=_round_count(
                source.get("max_negotiation_rounds"), "max_negotiation_rounds", 1
            ),
            max_replan_attempts=_round_count(
                source.get("max_replan_attempts"), "max_replan_attempts", 0
            ),
            fallback_action=fallback_action,
            human_review_on_failure=human_review_on_failure,
            action_space=action_space,
            reward_weights=MappingProxyType(reward_weights),
            experiment_tags=experiment_tags,
            config_hash=config_hash,
        )


def _config_hash(source: Mapping[str, Any]) -> str:
    payload = dict(source)
    payload.pop("config_hash", None)
    try:
        canonical_json = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("protocol profile must contain JSON-compatible values") from exc
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def load_research_protocol(path: str | Path) -> ResearchProtocolProfile:
    profile_path = Path(path)
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load protocol profile: {profile_path}") from exc
    return ResearchProtocolProfile.from_dict(data)


def load_protocol_profiles(
    directory: str | Path,
) -> dict[str, ResearchProtocolProfile]:
    profile_directory = Path(directory)
    if not profile_directory.exists():
        raise ValueError(
            f"protocol profile directory does not exist: {profile_directory}"
        )
    if not profile_directory.is_dir():
        raise ValueError(
            f"protocol profile path is not a directory: {profile_directory}"
        )

    profile_paths = sorted(profile_directory.glob("*.json"))
    if not profile_paths:
        raise ValueError(
            f"protocol profile directory contains no JSON profiles: {profile_directory}"
        )

    profiles: dict[str, ResearchProtocolProfile] = {}
    for path in profile_paths:
        profile = load_research_protocol(path)
        if profile.profile_id in profiles:
            raise ValueError(f"duplicate profile_id: {profile.profile_id}")
        profiles[profile.profile_id] = profile
    return profiles


def select_default_protocol_profile(
    profiles: Mapping[str, ResearchProtocolProfile],
) -> ResearchProtocolProfile:
    try:
        profile = profiles[DEFAULT_PROTOCOL_PROFILE_ID]
    except KeyError as exc:
        raise ValueError(
            "default protocol profile is missing: " + DEFAULT_PROTOCOL_PROFILE_ID
        ) from exc

    if profile.max_negotiation_rounds != 2:
        raise ValueError(
            "default protocol profile max_negotiation_rounds must be 2; got "
            + str(profile.max_negotiation_rounds)
        )
    if profile.max_replan_attempts != 1:
        raise ValueError(
            "default protocol profile max_replan_attempts must be 1; got "
            + str(profile.max_replan_attempts)
        )
    return profile

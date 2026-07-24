from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
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
        "capabilities",
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


def _list_value(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _number_value(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _integer_value(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _semantic_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty")


def _semantic_weight(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    if not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"{label} must not be negative")


def _semantic_round_count(
    value: Any,
    label: str,
    minimum: int,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be at least {minimum}")


def _validate_binding_semantics(binding: ProtocolAgentBinding) -> None:
    _semantic_text(binding.name, "agent name")
    _semantic_text(binding.implementation_id, "implementation_id")
    _semantic_text(binding.runtime, "runtime")
    if not isinstance(binding.enabled, bool):
        raise ValueError("enabled must be a boolean")
    if not isinstance(binding.veto_scopes, tuple) or not binding.veto_scopes:
        raise ValueError("veto_scopes must be a non-empty tuple")
    for scope in binding.veto_scopes:
        _semantic_text(scope, "veto scope")
    if len(set(binding.veto_scopes)) != len(binding.veto_scopes):
        raise ValueError("veto_scopes must not contain duplicates")
    _semantic_weight(binding.consensus_weight, "consensus_weight")
    if not isinstance(binding.capabilities, tuple) or not binding.capabilities:
        raise ValueError("capabilities must be a non-empty tuple")
    for capability in binding.capabilities:
        _semantic_text(capability, "capability")
    if len(set(binding.capabilities)) != len(binding.capabilities):
        raise ValueError("capabilities must not contain duplicates")


@dataclass(frozen=True)
class ProtocolAgentBinding:
    name: str
    implementation_id: str
    runtime: str
    enabled: bool
    veto_scopes: tuple[str, ...]
    consensus_weight: float
    capabilities: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProtocolAgentBinding:
        source = _require_mapping(data, "agent binding")
        unknown = set(source) - _BINDING_KEYS
        if unknown:
            raise ValueError(
                "agent binding contains unknown fields: "
                + ", ".join(sorted(unknown))
            )

        raw_scopes = _list_value(source.get("veto_scopes"), "veto_scopes")
        scopes = tuple(_required_text({"value": item}, "value", "veto scope") for item in raw_scopes)
        raw_capabilities = _list_value(
            source.get("capabilities"), "capabilities"
        )
        capabilities = tuple(
            _required_text({"value": item}, "value", "capability")
            for item in raw_capabilities
        )
        enabled = source.get("enabled")

        return cls(
            name=_required_text(source, "name", "agent name"),
            implementation_id=_required_text(
                source, "implementation_id", "implementation_id"
            ),
            runtime=_required_text(source, "runtime", "runtime"),
            enabled=enabled,
            veto_scopes=scopes,
            consensus_weight=_number_value(
                source.get("consensus_weight"), "consensus_weight"
            ),
            capabilities=capabilities,
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

    def to_canonical_dict(self) -> dict[str, Any]:
        return {
            **_canonical_profile_payload(self),
            "config_hash": self.config_hash,
        }

    def recomputed_config_hash(self) -> str:
        return _config_hash(_canonical_profile_payload(self))

    def validate_semantics(self) -> None:
        _semantic_text(self.profile_id, "profile_id")
        _semantic_text(self.version, "version")
        if not isinstance(self.agents, tuple) or not self.agents:
            raise ValueError("profile must contain at least one agent")

        agent_names: list[str] = []
        enabled_names: set[str] = set()
        for binding in self.agents:
            if not isinstance(binding, ProtocolAgentBinding):
                raise ValueError(
                    "agents must contain ProtocolAgentBinding values"
                )
            _validate_binding_semantics(binding)
            agent_names.append(binding.name)
            if binding.enabled:
                enabled_names.add(binding.name)
        if len(set(agent_names)) != len(agent_names):
            raise ValueError("duplicate agent name in profile")
        if not enabled_names:
            raise ValueError("profile must contain at least one enabled agent")

        if not isinstance(self.review_matrix, Mapping):
            raise ValueError("review_matrix must be an object")
        matrix_targets = set(self.review_matrix)
        known_agents = set(agent_names)
        if matrix_targets != known_agents:
            missing = sorted(known_agents - matrix_targets)
            unknown_targets = sorted(matrix_targets - known_agents)
            details = []
            if missing:
                details.append("missing targets: " + ", ".join(missing))
            if unknown_targets:
                details.append(
                    "unknown targets: " + ", ".join(unknown_targets)
                )
            raise ValueError(
                "review_matrix does not match agents ("
                + "; ".join(details)
                + ")"
            )
        for target, reviewers in self.review_matrix.items():
            _semantic_text(target, "review_matrix target")
            if not isinstance(reviewers, tuple) or not reviewers:
                raise ValueError(
                    f"reviewers for {target} must be a non-empty tuple"
                )
            for reviewer in reviewers:
                _semantic_text(reviewer, "review participant")
            unknown_reviewers = set(reviewers) - known_agents
            if unknown_reviewers:
                raise ValueError(
                    "unknown review participant: "
                    + ", ".join(sorted(unknown_reviewers))
                )
            if target in reviewers:
                raise ValueError(f"agent cannot self-review: {target}")
            if len(set(reviewers)) != len(reviewers):
                raise ValueError(
                    f"reviewers for {target} must not contain duplicates"
                )

        if not isinstance(self.consensus_strategy, ConsensusStrategy):
            raise ValueError("unknown consensus_strategy")
        _semantic_round_count(
            self.max_negotiation_rounds,
            "max_negotiation_rounds",
            1,
        )
        _semantic_round_count(
            self.max_replan_attempts,
            "max_replan_attempts",
            0,
        )
        if not isinstance(self.fallback_action, RecoveryActionKind):
            raise ValueError("unknown fallback_action")
        if self.fallback_action is not RecoveryActionKind.OBSERVE_ONLY:
            raise ValueError("fallback_action must be observe_only")
        if self.human_review_on_failure is not True:
            raise ValueError("human_review_on_failure must be true")

        if not isinstance(self.action_space, tuple) or not self.action_space:
            raise ValueError("action_space must be a non-empty tuple")
        if any(
            not isinstance(action, RecoveryActionKind)
            for action in self.action_space
        ):
            raise ValueError(
                "action_space contains an unknown recovery action"
            )
        if len(set(self.action_space)) != len(self.action_space):
            raise ValueError("action_space must not contain duplicates")
        if self.fallback_action not in self.action_space:
            raise ValueError(
                "fallback_action must be included in action_space"
            )

        if not isinstance(self.reward_weights, Mapping) or not self.reward_weights:
            raise ValueError("reward_weights must be a non-empty object")
        for name, weight in self.reward_weights.items():
            _semantic_text(name, "reward weight name")
            _semantic_weight(weight, f"reward_weights[{name}]")

        if (
            not isinstance(self.experiment_tags, tuple)
            or not self.experiment_tags
        ):
            raise ValueError("experiment_tags must be a non-empty tuple")
        for tag in self.experiment_tags:
            _semantic_text(tag, "experiment tag")
        if len(set(self.experiment_tags)) != len(self.experiment_tags):
            raise ValueError("experiment_tags must not contain duplicates")

    def validate_integrity(self) -> None:
        self.validate_semantics()
        expected = self.recomputed_config_hash()
        if self.config_hash != expected:
            raise ValueError(
                "config_hash does not match current profile contents"
            )

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
        if not isinstance(raw_agents, list):
            raise ValueError("agents must be a list")
        agents = tuple(ProtocolAgentBinding.from_dict(item) for item in raw_agents)

        matrix_source = _require_mapping(
            source.get("review_matrix"), "review_matrix"
        )

        matrix: dict[str, tuple[str, ...]] = {}
        for target, raw_reviewers in matrix_source.items():
            normalized_target = _required_text(
                {"value": target},
                "value",
                "review_matrix target",
            )
            reviewers = _list_value(
                raw_reviewers,
                f"reviewers for {normalized_target}",
            )
            normalized_reviewers = tuple(
                _required_text({"value": reviewer}, "value", "reviewer")
                for reviewer in reviewers
            )
            matrix[normalized_target] = normalized_reviewers

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

        human_review_on_failure = source.get("human_review_on_failure")

        raw_actions = _list_value(source.get("action_space"), "action_space")
        try:
            action_space = tuple(RecoveryActionKind(str(item)) for item in raw_actions)
        except ValueError as exc:
            raise ValueError("action_space contains an unknown recovery action") from exc

        reward_source = _require_mapping(
            source.get("reward_weights"), "reward_weights"
        )
        reward_weights = {
            _required_text(
                {"value": key},
                "value",
                "reward weight name",
            ): _number_value(value, f"reward_weights[{key}]")
            for key, value in reward_source.items()
        }

        raw_tags = _list_value(
            source.get("experiment_tags"),
            "experiment_tags",
        )
        experiment_tags = tuple(
            _required_text({"value": tag}, "value", "experiment tag")
            for tag in raw_tags
        )

        profile = cls(
            profile_id=_required_text(source, "profile_id", "profile_id"),
            version=_required_text(source, "version", "version"),
            agents=agents,
            review_matrix=MappingProxyType(matrix),
            consensus_strategy=consensus_strategy,
            max_negotiation_rounds=_integer_value(
                source.get("max_negotiation_rounds"),
                "max_negotiation_rounds",
            ),
            max_replan_attempts=_integer_value(
                source.get("max_replan_attempts"),
                "max_replan_attempts",
            ),
            fallback_action=fallback_action,
            human_review_on_failure=human_review_on_failure,
            action_space=action_space,
            reward_weights=MappingProxyType(reward_weights),
            experiment_tags=experiment_tags,
            config_hash="",
        )
        profile.validate_semantics()
        config_hash = profile.recomputed_config_hash()
        supplied_hash = source.get("config_hash")
        if supplied_hash is not None:
            if not isinstance(supplied_hash, str) or supplied_hash != config_hash:
                raise ValueError("config_hash does not match profile contents")
        return replace(profile, config_hash=config_hash)


def _canonical_profile_payload(
    profile: ResearchProtocolProfile,
) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "version": profile.version,
        "agents": [
            {
                "name": binding.name,
                "implementation_id": binding.implementation_id,
                "runtime": binding.runtime,
                "enabled": binding.enabled,
                "veto_scopes": list(binding.veto_scopes),
                "consensus_weight": binding.consensus_weight,
                "capabilities": list(binding.capabilities),
            }
            for binding in profile.agents
        ],
        "review_matrix": {
            target: list(reviewers)
            for target, reviewers in profile.review_matrix.items()
        },
        "consensus_strategy": profile.consensus_strategy.value,
        "max_negotiation_rounds": profile.max_negotiation_rounds,
        "max_replan_attempts": profile.max_replan_attempts,
        "fallback_action": profile.fallback_action.value,
        "human_review_on_failure": profile.human_review_on_failure,
        "action_space": [action.value for action in profile.action_space],
        "reward_weights": dict(profile.reward_weights),
        "experiment_tags": list(profile.experiment_tags),
    }


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
    profile.validate_integrity()
    return profile

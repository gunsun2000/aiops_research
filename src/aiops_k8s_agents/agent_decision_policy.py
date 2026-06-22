from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_AGENT_DECISION_POLICY = Path("config/agent_decision_policy.json")


class AgentDecisionPolicyError(ValueError):
    """Raised when the configurable agent decision policy is invalid."""


@dataclass(frozen=True)
class MetricPolicy:
    canonical_name: str
    aliases: tuple[str, ...]
    cause: str
    signal_direction: str
    warning_ratio: float
    critical_ratio: float

    @classmethod
    def from_dict(cls, canonical_name: str, data: dict[str, Any]) -> MetricPolicy:
        signal_direction = str(data.get("signal_direction", "")).strip()
        if signal_direction not in {"high_is_bad", "low_is_bad"}:
            raise AgentDecisionPolicyError(
                f"metric {canonical_name} must define high_is_bad or low_is_bad"
            )
        cause = str(data.get("cause", "")).strip()
        if not cause:
            raise AgentDecisionPolicyError(f"metric {canonical_name} cause is required")
        severity = dict(data.get("severity", {}))
        return cls(
            canonical_name=canonical_name,
            aliases=tuple(
                _normalize_metric(str(alias))
                for alias in data.get("aliases", [canonical_name])
            ),
            cause=cause,
            signal_direction=signal_direction,
            warning_ratio=float(severity.get("warning_ratio", 1.0)),
            critical_ratio=float(severity.get("critical_ratio", 1.10)),
        )

    def threshold_exceeded(self, value: float, threshold: float) -> bool:
        if self.signal_direction == "high_is_bad":
            return value >= threshold
        return value <= threshold

    def severity_score(self, value: float, threshold: float) -> float:
        if threshold <= 0:
            return 0.0
        if self.signal_direction == "high_is_bad":
            return value / threshold
        if value <= 0:
            return self.critical_ratio
        return threshold / value

    def severity_label(self, value: float, threshold: float) -> str:
        if not self.threshold_exceeded(value, threshold):
            return "info"
        score = self.severity_score(value, threshold)
        if score >= self.critical_ratio:
            return "critical"
        if score >= self.warning_ratio:
            return "warning"
        return "info"


@dataclass(frozen=True)
class AgentDecisionPolicy:
    version: str
    metric_policies: dict[str, MetricPolicy]
    preferred_actions: dict[str, str]
    action_rewards: dict[str, float]
    replica_by_severity: dict[str, int]
    default_replicas: int
    max_replicas: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDecisionPolicy:
        metrics = {
            str(name): MetricPolicy.from_dict(str(name), dict(raw))
            for name, raw in dict(data.get("metric_categories", {})).items()
        }
        if not metrics:
            raise AgentDecisionPolicyError("metric_categories must not be empty")
        replica_policy = dict(data.get("replica_recommendation_policy", {}))
        by_severity = {
            str(name): int(value)
            for name, value in dict(replica_policy.get("by_severity", {})).items()
        }
        return cls(
            version=str(data.get("version", "1")),
            metric_policies=metrics,
            preferred_actions={
                str(cause): str(action)
                for cause, action in dict(
                    data.get("preferred_actions_by_cause", {})
                ).items()
            },
            action_rewards={
                str(action): float(reward)
                for action, reward in dict(data.get("action_rewards", {})).items()
            },
            replica_by_severity=by_severity,
            default_replicas=int(replica_policy.get("default_replicas", 3)),
            max_replicas=int(replica_policy.get("max_replicas", 5)),
        )

    def metric_policy_for(self, metric: str) -> MetricPolicy | None:
        normalized = _normalize_metric(metric)
        for policy in self.metric_policies.values():
            if normalized == policy.canonical_name or normalized in policy.aliases:
                return policy
        return None

    def preferred_action_for(self, cause: str) -> str:
        return self.preferred_actions.get(cause, "scale_out")

    def reward_for(self, action: str, default: float) -> float:
        return self.action_rewards.get(action, default)

    def recommended_replicas(
        self,
        severity: str,
        current_replicas: int | None = None,
    ) -> int:
        target = self.replica_by_severity.get(severity, self.default_replicas)
        if current_replicas is not None:
            target = max(target, current_replicas + 1)
        return max(1, min(target, self.max_replicas))


def load_agent_decision_policy(
    path: str | Path = DEFAULT_AGENT_DECISION_POLICY,
) -> AgentDecisionPolicy:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return AgentDecisionPolicy.from_dict(data)


def default_agent_decision_policy() -> AgentDecisionPolicy:
    return load_agent_decision_policy(DEFAULT_AGENT_DECISION_POLICY)


def _normalize_metric(metric: str) -> str:
    return metric.strip().lower().replace("-", "_")

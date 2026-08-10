"""Optional, safety-bounded Action Policy learning for recovery experiments.

This module is deliberately advisory. It ranks the existing bounded recovery
actions from completed experiment outcomes; it does not execute Kubernetes
commands or bypass the four-Agent review and Validator boundary.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from aiops_k8s_agents.agent_decision_policy import default_agent_decision_policy


PolicyMode = Literal["baseline", "learned"]
ACTION_KINDS = ("observe_only", "rollout_restart", "scale_out")


@dataclass(frozen=True)
class PolicyContext:
    scenario: str
    metric: str = ""
    cause: str = ""
    severity: str = ""

    @property
    def key(self) -> str:
        return "|".join(
            _normalize(value)
            for value in (self.scenario, self.metric, self.cause, self.severity)
        )


@dataclass(frozen=True)
class PolicySample:
    context: PolicyContext
    action: str
    observed_reward: float
    recovery_success: bool
    safety_valid: bool
    measurement_valid: bool
    eligible: bool

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "PolicySample":
        action_data = record.get("action", {})
        action = (
            str(action_data.get("kind", ""))
            if isinstance(action_data, Mapping)
            else str(action_data)
        ).strip()
        scenario = str(record.get("scenario", "")).strip()
        metric = str(record.get("metric", "")).strip()
        cause = str(record.get("cause", "")).strip()
        if not cause:
            cause = _cause_for_metric(metric)
        context = PolicyContext(
            scenario=scenario,
            metric=metric,
            cause=cause,
            severity=str(record.get("severity", "")).strip(),
        )
        safety_valid = bool(record.get("safety_valid", True))
        measurement_valid = bool(record.get("measurement_valid", True))
        observed_reward = _record_reward(record)
        eligible = (
            action in ACTION_KINDS
            and safety_valid
            and measurement_valid
            and bool(scenario)
        )
        return cls(
            context=context,
            action=action,
            observed_reward=observed_reward,
            recovery_success=bool(record.get("recovery_success", False)),
            safety_valid=safety_valid,
            measurement_valid=measurement_valid,
            eligible=eligible,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.context.scenario,
            "metric": self.context.metric,
            "cause": self.context.cause,
            "severity": self.context.severity,
            "action": self.action,
            "observed_reward": round(self.observed_reward, 6),
            "recovery_success": self.recovery_success,
            "safety_valid": self.safety_valid,
            "measurement_valid": self.measurement_valid,
            "eligible": self.eligible,
        }


@dataclass(frozen=True)
class PolicyRecommendation:
    policy_mode: PolicyMode
    context: PolicyContext
    selected_action: str
    ranking: tuple[dict[str, Any], ...]
    training_samples: int
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_mode": self.policy_mode,
            "context": {
                "scenario": self.context.scenario,
                "metric": self.context.metric,
                "cause": self.context.cause,
                "severity": self.context.severity,
            },
            "selected_action": self.selected_action,
            "ranking": [dict(row) for row in self.ranking],
            "training_samples": self.training_samples,
            "fallback_reason": self.fallback_reason,
            "advisory_only": True,
            "safety_boundary": "4-agent-review-and-validator",
        }


class ContextualBanditPolicy:
    """Rank bounded actions from observed rewards with a baseline fallback."""

    def __init__(self, mode: PolicyMode = "baseline") -> None:
        if mode not in {"baseline", "learned"}:
            raise ValueError("policy mode must be baseline or learned")
        self.mode = mode
        self._context_rewards: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._global_rewards: dict[str, list[float]] = defaultdict(list)
        self._sample_count = 0

    @property
    def training_samples(self) -> int:
        return self._sample_count

    def fit(self, samples: Iterable[PolicySample]) -> None:
        self._context_rewards.clear()
        self._global_rewards.clear()
        self._sample_count = 0
        for sample in samples:
            if not sample.eligible:
                continue
            self._context_rewards[sample.context.key][sample.action].append(
                sample.observed_reward
            )
            self._global_rewards[sample.action].append(sample.observed_reward)
            self._sample_count += 1

    def recommend(self, context: PolicyContext) -> PolicyRecommendation:
        baseline_action = default_agent_decision_policy().preferred_action_for(
            context.cause
        )
        if baseline_action not in ACTION_KINDS:
            baseline_action = "observe_only"

        fallback_reason = ""
        ranking: list[dict[str, Any]] = []
        context_rewards = self._context_rewards.get(context.key, {})
        if self.mode == "learned" and self._sample_count:
            for action in ACTION_KINDS:
                values = context_rewards.get(action)
                source = "context"
                if not values:
                    values = self._global_rewards.get(action, [])
                    source = "global" if values else "baseline"
                mean_reward = (
                    _mean(values)
                    if values
                    else (1.0 if action == baseline_action else 0.0)
                )
                ranking.append(
                    {
                        "action": action,
                        "mean_reward": round(mean_reward, 6),
                        "samples": len(values) if values else 0,
                        "source": source,
                    }
                )
        else:
            if self.mode == "learned":
                fallback_reason = "no eligible training samples"
            for action in ACTION_KINDS:
                ranking.append(
                    {
                        "action": action,
                        "mean_reward": 1.0 if action == baseline_action else 0.0,
                        "samples": 0,
                        "source": "baseline",
                    }
                )

        ranking.sort(
            key=lambda row: (
                -float(row["mean_reward"]),
                0 if row["action"] == baseline_action else 1,
                ACTION_KINDS.index(row["action"]),
            )
        )
        return PolicyRecommendation(
            policy_mode=self.mode,
            context=context,
            selected_action=str(ranking[0]["action"]),
            ranking=tuple(ranking),
            training_samples=self._sample_count,
            fallback_reason=fallback_reason,
        )


def load_policy_samples(path: str | Path) -> list[PolicySample]:
    samples: list[PolicySample] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, Mapping):
                raise TypeError("record must be an object")
            samples.append(PolicySample.from_record(record))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid policy sample at line {line_number}: {exc}"
            ) from exc
    return samples


def write_policy_samples(
    samples: Iterable[PolicySample],
    path: str | Path,
) -> dict[str, Any]:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(samples)
    output_path.write_text(
        "".join(
            json.dumps(sample.to_dict(), ensure_ascii=False, sort_keys=True)
            + "\n"
            for sample in materialized
        ),
        encoding="utf-8",
    )
    return {
        "output": str(output_path),
        "total_samples": len(materialized),
        "eligible_samples": sum(sample.eligible for sample in materialized),
    }


def _record_reward(record: Mapping[str, Any]) -> float:
    evaluation = record.get("evaluation")
    if isinstance(evaluation, Mapping):
        for key in ("team_reward", "observed_reward"):
            if key in evaluation:
                return _clamp(float(evaluation[key]))
    for key in ("observed_reward", "team_reward", "reward"):
        if key in record:
            return _clamp(float(record[key]))

    if not bool(record.get("safety_valid", True)) or not bool(
        record.get("measurement_valid", True)
    ):
        return -1.0
    success = 1.0 if bool(record.get("recovery_success", False)) else 0.0
    availability = _unit(record.get("availability_recovery", 0.0))
    improvement = _unit(record.get("metric_improvement", 0.0))
    recovery_seconds = max(float(record.get("recovery_seconds", 60.0)), 0.0)
    time_score = 1.0 - _unit(recovery_seconds / 60.0)
    replica_penalty = _unit(max(int(record.get("replica_delta", 0)), 0) / 4.0)
    return _clamp(
        0.45 * success
        + 0.20 * availability
        + 0.20 * improvement
        + 0.10 * time_score
        + 0.05 * (1.0 - replica_penalty)
    )


def _cause_for_metric(metric: str) -> str:
    policy = default_agent_decision_policy().metric_policy_for(metric)
    return policy.cause if policy is not None else "unknown_metric"


def cause_for_metric(metric: str) -> str:
    """Return the registered cause without exposing the policy internals."""

    return _cause_for_metric(metric)


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _unit(value: Any) -> float:
    return max(0.0, min(1.0, float(value)))


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))

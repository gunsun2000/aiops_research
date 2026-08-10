from __future__ import annotations

from dataclasses import dataclass
from typing import Any


AIOPSLAB_AGENT_NAMES = (
    "AIServiceHASupportAgent",
    "AIApplicationManagementAgent",
    "AISemiconductorInfraOpsAgent",
    "CostOptimizationAgent",
)


@dataclass(frozen=True)
class AIOpsLabEvaluation:
    evaluator: str
    rubric_version: str
    team_reward: float
    agent_rewards: dict[str, float]
    components: dict[str, float | None]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluator": self.evaluator,
            "rubric_version": self.rubric_version,
            "team_reward": self.team_reward,
            "agent_rewards": dict(self.agent_rewards),
            "components": dict(self.components),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AIOpsLabEvaluatorAgent:
    max_steps: int
    metrics_duration_minutes: int
    name: str = "AIOpsLabEvaluatorAgent"
    rubric_version: str = "evaluator-v1"

    def evaluate(
        self,
        aiopslab_results: dict[str, Any],
        decisions: list[dict[str, Any]],
    ) -> AIOpsLabEvaluation:
        raw_results = dict(aiopslab_results.get("results", {}))
        accuracy = str(raw_results.get("Detection Accuracy", "")).strip()
        correctness = _correctness_score(accuracy)
        ttd_efficiency = _ttd_efficiency(
            _optional_float(raw_results.get("TTD")),
            self.metrics_duration_minutes,
        )
        step_efficiency = _step_efficiency(
            _optional_float(raw_results.get("steps")),
            self.max_steps,
        )
        efficiency = _mean_available(ttd_efficiency, step_efficiency)
        safety = _safety_score(decisions)
        evidence_quality = _evidence_quality(decisions)

        team_reward = _clamp(
            0.65 * correctness
            + 0.15 * efficiency
            + 0.10 * safety
            + 0.10 * evidence_quality
        )
        role_scores = {
            "AIServiceHASupportAgent": correctness,
            "AIApplicationManagementAgent": _clamp(
                0.60 * correctness + 0.40 * evidence_quality
            ),
            "AISemiconductorInfraOpsAgent": safety,
            "CostOptimizationAgent": efficiency,
        }
        agent_rewards = {
            agent: _round_reward(0.70 * team_reward + 0.30 * role_scores[agent])
            for agent in AIOPSLAB_AGENT_NAMES
        }
        components: dict[str, float | None] = {
            "correctness": correctness,
            "ttd_efficiency": ttd_efficiency,
            "step_efficiency": step_efficiency,
            "efficiency": efficiency,
            "safety": safety,
            "evidence_quality": evidence_quality,
        }
        reason = (
            f"Detection Accuracy={accuracy or 'unavailable'}; "
            f"efficiency={efficiency:.3f}; safety={safety:.3f}; "
            f"evidence_quality={evidence_quality:.3f}."
        )
        return AIOpsLabEvaluation(
            evaluator=self.name,
            rubric_version=self.rubric_version,
            team_reward=_round_reward(team_reward),
            agent_rewards=agent_rewards,
            components=components,
            reason=reason,
        )


def attach_aiopslab_evaluation(
    report: dict[str, Any],
    *,
    max_steps: int,
    metrics_duration_minutes: int,
) -> dict[str, Any]:
    decisions = list(report.get("decisions", []))
    for decision in decisions:
        metadata = dict(decision.get("metadata", {}))
        metadata.pop("rewards", None)
        metadata.pop("reward_total", None)
        decision["metadata"] = metadata

    evaluator = AIOpsLabEvaluatorAgent(
        max_steps=max_steps,
        metrics_duration_minutes=metrics_duration_minutes,
    )
    evaluation = evaluator.evaluate(
        dict(report.get("aiopslab_results", {})),
        decisions,
    )
    report["decisions"] = decisions
    report["evaluation"] = evaluation.to_dict()
    return report


def _correctness_score(accuracy: str) -> float:
    normalized = accuracy.strip().lower()
    if normalized == "correct":
        return 1.0
    if normalized == "incorrect":
        return -1.0
    return 0.0


def _ttd_efficiency(ttd: float | None, metrics_duration_minutes: int) -> float | None:
    if ttd is None:
        return None
    budget_seconds = max(float(metrics_duration_minutes) * 60.0, 1.0)
    ratio = max(ttd, 0.0) / budget_seconds
    return _round_component(1.0 - min(ratio, 1.0) * 2.0)


def _step_efficiency(steps: float | None, max_steps: int) -> float | None:
    if steps is None:
        return None
    budget = max(float(max_steps), 1.0)
    normalized_steps = min(max(steps, 1.0), budget)
    if budget <= 1.0:
        return 1.0
    progress = (normalized_steps - 1.0) / (budget - 1.0)
    return _round_component(1.0 - 2.0 * progress)


def _mean_available(*values: float | None) -> float:
    available = [value for value in values if value is not None]
    if not available:
        return 0.0
    return _round_component(sum(available) / len(available))


def _safety_score(decisions: list[dict[str, Any]]) -> float:
    if not decisions:
        return 0.0
    for decision in decisions:
        metadata = dict(decision.get("metadata", {}))
        if decision.get("valid") is False or metadata.get("referee") == "rejected":
            return -1.0
    return 1.0


def _evidence_quality(decisions: list[dict[str, Any]]) -> float:
    calls = [str(decision.get("api_call", "")).strip() for decision in decisions]
    has_logs = any(call.startswith("get_logs(") for call in calls)
    has_metrics = any(call.startswith("get_metrics(") for call in calls)
    if has_logs and has_metrics:
        return 1.0
    if has_logs or has_metrics:
        return 0.5
    return 0.0


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _round_component(value: float) -> float:
    return round(_clamp(value), 6)


def _round_reward(value: float) -> float:
    return round(_clamp(value), 6)

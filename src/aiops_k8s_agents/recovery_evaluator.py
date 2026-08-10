"""Post-run evaluator for recovery experiments.

The evaluator is intentionally independent from the decision-time agent
contribution values.  Those values describe the reasoning trace; this module
scores the completed experiment from the evidence that the runtime actually
recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


RECOVERY_AGENT_NAMES = (
    "AIServiceHASupportAgent",
    "AIApplicationManagementAgent",
    "AISemiconductorInfraOpsAgent",
    "CostOptimizationAgent",
)


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if isfinite(value) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (list, tuple, set, Mapping)):
        return len(value)
    number = _number(value)
    return max(0, int(number)) if number is not None else 0


def _outcome(report: Mapping[str, Any]) -> float:
    status = str(report.get("final_status", "")).strip().lower()
    recovery = _mapping(report.get("recovery_monitoring"))
    recovery_success = recovery.get("recovery_success")
    if recovery_success is None:
        recovery_success = recovery.get("recovered")

    if status == "safe_stopped":
        return -0.25
    if status in {
        "safe_failure",
        "failed",
        "consensus_rejected",
        "configuration_rejected",
        "interrupted",
        "cancelled",
    }:
        return -1.0
    if recovery_success is False:
        return -1.0
    if status == "recovered_after_replan":
        return 0.75
    if status in {"recovered", "no_action_required"} or recovery_success is True:
        return 1.0
    return 0.0


def _efficiency(report: Mapping[str, Any]) -> float:
    replans = _count(report.get("replanning_attempts"))
    actions = _count(report.get("executed_actions"))
    monitoring = _mapping(report.get("recovery_monitoring"))
    execution = _mapping(report.get("execution_result"))
    steps = _count(
        monitoring.get(
            "actual_steps",
            monitoring.get("steps", report.get("actual_steps", execution.get("steps"))),
        )
    )

    signals = replans or actions or steps
    if not signals:
        return 0.0

    score = 1.0
    score -= 0.20 * replans
    score -= 0.15 * max(actions - 1, 0)
    score -= 0.10 * max(steps - 1, 0)

    # Recovery time is normalized only when the report contains an explicit
    # budget.  An observed duration by itself is not evidence of efficiency.
    recovery_seconds = _number(monitoring.get("recovery_seconds"))
    budget = _number(
        monitoring.get(
            "recovery_budget_seconds",
            report.get("recovery_budget_seconds"),
        )
    )
    if budget is None:
        protocol = _mapping(report.get("protocol_config"))
        if not protocol:
            protocol = _mapping(report.get("protocol"))
        budget = _number(protocol.get("recovery_budget_seconds"))
    if recovery_seconds is not None and budget is not None and budget > 0:
        score -= 0.20 * max(0.0, min(1.0, recovery_seconds / budget))
    return _clamp(score)


def _explicit_invalid(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("valid") is False:
            return True
        return any(_explicit_invalid(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_explicit_invalid(item) for item in value)
    return False


def _safety(report: Mapping[str, Any]) -> float:
    safety = _mapping(report.get("safety_validation"))
    execution = _mapping(report.get("execution_result"))
    executed = _count(report.get("executed_actions")) > 0

    if _explicit_invalid(safety):
        return -1.0 if executed else -0.5
    if execution.get("unsafe_execution") is True:
        return -1.0
    if execution.get("valid") is False:
        return -1.0 if executed else -0.5

    safety_valid = safety.get("valid")
    execution_valid = execution.get("valid")
    if safety_valid is True and execution_valid is not False:
        return 1.0
    if safety_valid is False:
        return -1.0 if executed else -0.5
    return 0.0


def _evidence_quality(report: Mapping[str, Any]) -> float:
    evidence = _mapping(report.get("evidence"))
    diagnosis = _mapping(report.get("diagnosis"))
    monitoring = _mapping(report.get("recovery_monitoring"))

    initial_complete = bool(
        evidence
        and evidence.get("metric_values")
        and evidence.get("source")
        and evidence.get("namespace")
        and evidence.get("deployment")
    )
    diagnosis_complete = bool(diagnosis and diagnosis.get("cause"))
    recovery_complete = any(
        key in monitoring and monitoring.get(key) is not None
        for key in ("recovery_success", "recovered", "recovery_seconds")
    )
    return (int(initial_complete) + int(diagnosis_complete) + int(recovery_complete)) / 3.0


def _cost_evidence_present(report: Mapping[str, Any]) -> bool:
    keys = {
        "cost",
        "cost_per_hour",
        "resource_cost",
        "cost_metrics",
        "cost_evidence",
    }
    for container in (
        report,
        _mapping(report.get("evidence")),
        _mapping(report.get("execution_result")),
    ):
        if any(key in container for key in keys):
            return True
    return False


@dataclass(frozen=True)
class RecoveryEvaluation:
    evaluator: str
    rubric_version: str
    team_reward: float
    agent_rewards: Mapping[str, float]
    components: Mapping[str, float]
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


class RecoveryEvaluatorAgent:
    """Evaluate the completed recovery outcome, not the proposal trace."""

    name = "RecoveryEvaluatorAgent"
    rubric_version = "recovery-evaluator-v1"

    def evaluate(self, report: Mapping[str, Any]) -> RecoveryEvaluation:
        outcome = _outcome(report)
        efficiency = _efficiency(report)
        safety = _safety(report)
        evidence_quality = _evidence_quality(report)
        components = {
            "outcome": _clamp(outcome),
            "efficiency": _clamp(efficiency),
            "safety": _clamp(safety),
            "evidence_quality": _clamp(evidence_quality),
        }
        team_reward = _clamp(
            0.65 * components["outcome"]
            + 0.15 * components["efficiency"]
            + 0.10 * components["safety"]
            + 0.10 * components["evidence_quality"]
        )
        if components["outcome"] < 0:
            team_reward = min(team_reward, 0.0)

        role_scores = {
            RECOVERY_AGENT_NAMES[0]: _clamp(
                (components["outcome"] + components["evidence_quality"]) / 2
            ),
            RECOVERY_AGENT_NAMES[1]: _clamp(
                (components["outcome"] + components["efficiency"]) / 2
            )
            if report.get("selected_action") or report.get("executed_actions")
            else 0.0,
            RECOVERY_AGENT_NAMES[2]: components["safety"],
            RECOVERY_AGENT_NAMES[3]: components["efficiency"]
            if not _cost_evidence_present(report)
            else _clamp((components["efficiency"] + components["safety"]) / 2),
        }
        agent_rewards = {
            agent: _clamp(0.70 * team_reward + 0.30 * role_scores[agent])
            for agent in RECOVERY_AGENT_NAMES
        }
        status = str(report.get("final_status", "unknown"))
        reason = (
            f"{status}: outcome={components['outcome']:.3f}, "
            f"efficiency={components['efficiency']:.3f}, "
            f"safety={components['safety']:.3f}, "
            f"evidence_quality={components['evidence_quality']:.3f}"
        )
        return RecoveryEvaluation(
            evaluator=self.name,
            rubric_version=self.rubric_version,
            team_reward=team_reward,
            agent_rewards=agent_rewards,
            components=components,
            reason=reason,
        )


def attach_recovery_evaluation(report: dict[str, Any]) -> dict[str, Any]:
    """Attach the authoritative post-run evaluation to a mutable report."""

    report["evaluation"] = RecoveryEvaluatorAgent().evaluate(report).to_dict()
    return report

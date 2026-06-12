from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiops_k8s_agents.models import RecoveryAction, RecoveryActionKind


@dataclass(frozen=True)
class RewardWeights:
    ha: float
    application: float
    infrastructure: float
    cost: float

    def __post_init__(self) -> None:
        values = (self.ha, self.application, self.infrastructure, self.cost)
        if any(value < 0 for value in values):
            raise ValueError("reward weights must be non-negative")
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("reward weights must sum to 1.0")


RECOVERY_REWARD_POLICIES: dict[str, RewardWeights] = {
    "balanced": RewardWeights(0.30, 0.30, 0.20, 0.20),
    "ha_first": RewardWeights(0.50, 0.25, 0.15, 0.10),
    "cost_first": RewardWeights(0.25, 0.20, 0.15, 0.40),
    "infra_first": RewardWeights(0.25, 0.20, 0.40, 0.15),
}


@dataclass(frozen=True)
class RecoveryOutcome:
    scenario: str
    action: RecoveryAction
    recovery_success: float
    availability_recovery: float
    metric_improvement: float
    recovery_seconds: float
    replica_delta: int
    command_count: int
    safety_valid: bool
    measurement_valid: bool


@dataclass(frozen=True)
class ActionEvaluation:
    outcome: RecoveryOutcome
    weights: RewardWeights
    ha_score: float
    application_score: float
    infrastructure_score: float
    cost_score: float
    predicted_reward: float
    observed_outcome_score: float


def evaluate_recovery_action(
    outcome: RecoveryOutcome,
    weights: RewardWeights,
) -> ActionEvaluation:
    if not outcome.safety_valid or not outcome.measurement_valid:
        return ActionEvaluation(
            outcome=outcome,
            weights=weights,
            ha_score=0.0,
            application_score=0.0,
            infrastructure_score=0.0,
            cost_score=0.0,
            predicted_reward=-1.0,
            observed_outcome_score=0.0,
        )

    availability = _unit(outcome.availability_recovery)
    metric_improvement = _unit(outcome.metric_improvement)
    time_score = 1.0 - _unit(max(outcome.recovery_seconds, 0.0) / 60.0)
    replica_overhead = _unit(max(outcome.replica_delta, 0) / 4.0)

    ha_score = 0.60 * float(outcome.recovery_success) + 0.40 * availability
    application_score = 0.55 * metric_improvement + 0.45 * time_score
    infrastructure_score = max(
        0.0,
        1.0
        - replica_overhead
        - min(max(outcome.command_count - 1, 0) * 0.05, 0.25),
    )
    cost_score = _cost_score(outcome.action.kind, outcome.replica_delta)
    predicted_reward = (
        weights.ha * ha_score
        + weights.application * application_score
        + weights.infrastructure * infrastructure_score
        + weights.cost * cost_score
    )
    observed_outcome_score = (
        ha_score + application_score + infrastructure_score + cost_score
    ) / 4.0

    return ActionEvaluation(
        outcome=outcome,
        weights=weights,
        ha_score=round(ha_score, 6),
        application_score=round(application_score, 6),
        infrastructure_score=round(infrastructure_score, 6),
        cost_score=round(cost_score, 6),
        predicted_reward=round(predicted_reward, 6),
        observed_outcome_score=round(observed_outcome_score, 6),
    )


def rank_recovery_actions(
    outcomes: list[RecoveryOutcome],
    weights: RewardWeights,
) -> list[ActionEvaluation]:
    evaluations = [evaluate_recovery_action(outcome, weights) for outcome in outcomes]
    return sorted(
        evaluations,
        key=lambda item: (
            -item.predicted_reward,
            max(item.outcome.replica_delta, 0),
            item.outcome.command_count,
            item.outcome.action.kind.value,
        ),
    )


def load_recovery_outcomes(path: str | Path) -> list[RecoveryOutcome]:
    outcomes: list[RecoveryOutcome] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            outcomes.append(_outcome_from_dict(data))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid recovery outcome at line {line_number}: {exc}") from exc
    if not outcomes:
        raise ValueError("recovery outcome file is empty")
    return outcomes


def analyze_recovery_outcomes(
    outcomes: list[RecoveryOutcome],
) -> dict[str, Any]:
    aggregated = _aggregate_repetitions(outcomes)
    scenarios = sorted({outcome.scenario for outcome in aggregated})
    policies: dict[str, dict[str, Any]] = {}
    for policy_name, weights in RECOVERY_REWARD_POLICIES.items():
        policy_scenarios: dict[str, Any] = {}
        for scenario in scenarios:
            ranking = rank_recovery_actions(
                [outcome for outcome in aggregated if outcome.scenario == scenario],
                weights,
            )
            policy_scenarios[scenario] = {
                "selected_action": ranking[0].outcome.action.kind.value,
                "ranking": [_evaluation_to_dict(item, rank) for rank, item in enumerate(ranking, 1)],
            }
        policies[policy_name] = policy_scenarios
    return {
        "command": "score-recovery-experiments",
        "input_records": len(outcomes),
        "aggregated_candidates": len(aggregated),
        "policies": policies,
    }


def write_recovery_analysis(report: dict[str, Any], output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "reward_policy_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = list(_analysis_rows(report))
    with (output_path / "reward_policy_comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "policy",
                "scenario",
                "rank",
                "action",
                "predicted_reward",
                "observed_outcome_score",
                "ha_score",
                "application_score",
                "infrastructure_score",
                "cost_score",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    (output_path / "reward_policy_comparison.md").write_text(
        _render_analysis_markdown(report),
        encoding="utf-8",
    )


def _outcome_from_dict(data: dict[str, Any]) -> RecoveryOutcome:
    action_data = data["action"]
    action = RecoveryAction(
        namespace=str(action_data["namespace"]),
        deployment=str(action_data["deployment"]),
        kind=RecoveryActionKind(str(action_data["kind"])),
        replicas=(
            None if action_data.get("replicas") is None else int(action_data["replicas"])
        ),
        reason=str(action_data.get("reason", "")),
    )
    return RecoveryOutcome(
        scenario=str(data["scenario"]),
        action=action,
        recovery_success=float(data["recovery_success"]),
        availability_recovery=float(data["availability_recovery"]),
        metric_improvement=float(data["metric_improvement"]),
        recovery_seconds=float(data["recovery_seconds"]),
        replica_delta=int(data["replica_delta"]),
        command_count=int(data["command_count"]),
        safety_valid=bool(data["safety_valid"]),
        measurement_valid=bool(data["measurement_valid"]),
    )


def _aggregate_repetitions(outcomes: list[RecoveryOutcome]) -> list[RecoveryOutcome]:
    grouped: dict[tuple[str, RecoveryActionKind], list[RecoveryOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault((outcome.scenario, outcome.action.kind), []).append(outcome)

    aggregated: list[RecoveryOutcome] = []
    for values in grouped.values():
        first = values[0]
        count = len(values)
        aggregated.append(
            RecoveryOutcome(
                scenario=first.scenario,
                action=first.action,
                recovery_success=sum(float(item.recovery_success) for item in values) / count,
                availability_recovery=sum(item.availability_recovery for item in values) / count,
                metric_improvement=sum(item.metric_improvement for item in values) / count,
                recovery_seconds=sum(item.recovery_seconds for item in values) / count,
                replica_delta=round(sum(item.replica_delta for item in values) / count),
                command_count=round(sum(item.command_count for item in values) / count),
                safety_valid=all(item.safety_valid for item in values),
                measurement_valid=all(item.measurement_valid for item in values),
            )
        )
    return aggregated


def _evaluation_to_dict(item: ActionEvaluation, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "action": item.outcome.action.kind.value,
        "predicted_reward": item.predicted_reward,
        "observed_outcome_score": item.observed_outcome_score,
        "ha_score": item.ha_score,
        "application_score": item.application_score,
        "infrastructure_score": item.infrastructure_score,
        "cost_score": item.cost_score,
    }


def _analysis_rows(report: dict[str, Any]):
    for policy, scenarios in report["policies"].items():
        for scenario, result in scenarios.items():
            for item in result["ranking"]:
                yield {"policy": policy, "scenario": scenario, **item}


def _render_analysis_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Recovery Action and Reward Policy Comparison",
        "",
        f"- input_records: {report['input_records']}",
        f"- aggregated_candidates: {report['aggregated_candidates']}",
        "",
        "| policy | scenario | selected action | ranking |",
        "| --- | --- | --- | --- |",
    ]
    for policy, scenarios in report["policies"].items():
        for scenario, result in scenarios.items():
            ranking = ", ".join(
                f"{item['rank']}. {item['action']} ({item['predicted_reward']:.3f})"
                for item in result["ranking"]
            )
            lines.append(
                f"| {policy} | {scenario} | {result['selected_action']} | {ranking} |"
            )
    lines.append("")
    return "\n".join(lines)


def _cost_score(kind: RecoveryActionKind, replica_delta: int) -> float:
    if kind == RecoveryActionKind.OBSERVE_ONLY:
        return 1.0
    if kind == RecoveryActionKind.ROLLOUT_RESTART:
        return 0.65
    return max(0.10, 0.75 - 0.25 * max(replica_delta, 0))


def _unit(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)

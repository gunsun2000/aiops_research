from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from aiops_k8s_agents.aiopslab_evaluator import AIOPSLAB_AGENT_NAMES
from aiops_k8s_agents.research_framework import AIOPS_PHASE_ORDER, infer_aiopslab_api_phase


METRIC_PATH_PATTERN = re.compile(r"Metrics data exported to directory:\s*(\S+)")


@dataclass(frozen=True)
class AIOpsLabRunRecord:
    run_index: int
    file: str
    problem_id: str
    namespace: str
    service: str
    detection_accuracy: str
    ttd: float | None
    steps: int | None
    final_reward: float | None
    team_reward: float | None
    agent_rewards: dict[str, float]
    phase_coverage: str
    metric_exported: bool
    metric_path: str
    final_state: str


@dataclass(frozen=True)
class AIOpsLabSummary:
    records: list[AIOpsLabRunRecord]
    total_runs: int
    correct_runs: int
    metric_success_runs: int
    average_ttd: float | None
    average_steps: float | None
    average_final_reward: float | None
    average_team_reward: float | None
    average_agent_rewards: dict[str, float | None]


def summarize_aiopslab_reports(runs_dir: str | Path) -> AIOpsLabSummary:
    paths = sorted(Path(runs_dir).glob("*_aiopslab_auto_detection.json"))
    records = [
        _record_from_report(index=index, path=path)
        for index, path in enumerate(paths, start=1)
    ]
    average_team_reward = _mean(record.team_reward for record in records)
    return AIOpsLabSummary(
        records=records,
        total_runs=len(records),
        correct_runs=sum(1 for record in records if record.detection_accuracy == "Correct"),
        metric_success_runs=sum(1 for record in records if record.metric_exported),
        average_ttd=_mean(record.ttd for record in records),
        average_steps=_mean(record.steps for record in records),
        average_final_reward=average_team_reward,
        average_team_reward=average_team_reward,
        average_agent_rewards={
            agent: _mean(record.agent_rewards.get(agent) for record in records)
            for agent in AIOPSLAB_AGENT_NAMES
        },
    )


def write_aiopslab_summary_files(
    summary: AIOpsLabSummary,
    markdown_path: str | Path,
    csv_path: str | Path,
) -> None:
    markdown_path = Path(markdown_path)
    csv_path = Path(csv_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown_summary(summary), encoding="utf-8")
    _write_csv_summary(summary, csv_path)


def render_markdown_summary(summary: AIOpsLabSummary) -> str:
    lines = [
        "# AIOpsLab 4-Agent Detection 반복 실험 요약",
        "",
        "## Aggregate",
        "",
        f"- total_runs: {summary.total_runs}",
        f"- correct_runs: {summary.correct_runs}",
        f"- metric_success_runs: {summary.metric_success_runs}",
        f"- average_ttd_seconds: {_format_optional_float(summary.average_ttd)}",
        f"- average_steps: {_format_optional_float(summary.average_steps)}",
        f"- average_team_reward: {_format_optional_float(summary.average_team_reward)}",
        f"- average_HA_reward: {_format_optional_float(summary.average_agent_rewards.get('AIServiceHASupportAgent'))}",
        f"- average_APP_reward: {_format_optional_float(summary.average_agent_rewards.get('AIApplicationManagementAgent'))}",
        f"- average_Infra_reward: {_format_optional_float(summary.average_agent_rewards.get('AISemiconductorInfraOpsAgent'))}",
        f"- average_Cost_reward: {_format_optional_float(summary.average_agent_rewards.get('CostOptimizationAgent'))}",
        "",
        "## Runs",
        "",
        "| run | accuracy | TTD(s) | steps | team reward | HA reward | APP reward | Infra reward | Cost reward | phases | metric | report |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for record in summary.records:
        lines.append(
            (
                f"| {record.run_index} | {record.detection_accuracy} | "
                f"{_format_optional_float(record.ttd)} | "
                f"{record.steps if record.steps is not None else ''} | "
                f"{_format_optional_reward(record.team_reward)} | "
                f"{_format_optional_reward(record.agent_rewards.get('AIServiceHASupportAgent'))} | "
                f"{_format_optional_reward(record.agent_rewards.get('AIApplicationManagementAgent'))} | "
                f"{_format_optional_reward(record.agent_rewards.get('AISemiconductorInfraOpsAgent'))} | "
                f"{_format_optional_reward(record.agent_rewards.get('CostOptimizationAgent'))} | "
                f"{record.phase_coverage} | "
                f"{'yes' if record.metric_exported else 'no'} | "
                f"{record.file} |"
            )
        )
    lines.append("")
    return "\n".join(lines)


def _record_from_report(index: int, path: Path) -> AIOpsLabRunRecord:
    data = json.loads(path.read_text(encoding="utf-8"))
    aiopslab_results = data.get("aiopslab_results", {})
    metrics = aiopslab_results.get("results", {})
    decisions = list(data.get("decisions", []))
    evaluation = dict(data.get("evaluation", {}))
    metric_path = _extract_metric_path(decisions, aiopslab_results)
    team_reward = _optional_float(evaluation.get("team_reward"))
    agent_rewards = _extract_agent_rewards(evaluation)
    phase_coverage = _extract_phase_coverage(decisions)
    return AIOpsLabRunRecord(
        run_index=index,
        file=path.name,
        problem_id=str(data.get("problem_id", "")),
        namespace=str(data.get("namespace", "")),
        service=str(data.get("service", "")),
        detection_accuracy=str(metrics.get("Detection Accuracy", "")),
        ttd=_optional_float(metrics.get("TTD")),
        steps=_optional_int(metrics.get("steps")),
        final_reward=team_reward,
        team_reward=team_reward,
        agent_rewards=agent_rewards,
        phase_coverage=phase_coverage,
        metric_exported=bool(metric_path),
        metric_path=metric_path,
        final_state=str(aiopslab_results.get("final_state", "")),
    )


def _extract_agent_rewards(evaluation: dict[str, Any]) -> dict[str, float]:
    raw = dict(evaluation.get("agent_rewards", {}))
    rewards: dict[str, float] = {}
    for agent in AIOPSLAB_AGENT_NAMES:
        value = _optional_float(raw.get(agent))
        if value is not None:
            rewards[agent] = value
    return rewards


def _extract_metric_path(decisions: list[dict[str, Any]], aiopslab_results: dict[str, Any]) -> str:
    search_texts: list[str] = []
    search_texts.extend(str(decision.get("observation_excerpt", "")) for decision in decisions)
    search_texts.extend(str(item) for item in aiopslab_results.get("history", []))
    for text in search_texts:
        match = METRIC_PATH_PATTERN.search(text)
        if match:
            return match.group(1)
    return ""


def _extract_phase_coverage(decisions: list[dict[str, Any]]) -> str:
    phases: set[str] = set()
    for decision in decisions:
        metadata = dict(decision.get("metadata", {}))
        phase = str(metadata.get("phase", "")).strip()
        if not phase:
            phase = infer_aiopslab_api_phase(str(decision.get("api_call", "")))
        if phase:
            phases.add(phase)
    ordered = [phase for phase in AIOPS_PHASE_ORDER if phase in phases]
    return "+".join(ordered)


def _write_csv_summary(summary: AIOpsLabSummary, csv_path: Path) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "run_index",
                "file",
                "detection_accuracy",
                "ttd",
                "steps",
                "final_reward",
                "team_reward",
                "ha_reward",
                "app_reward",
                "infra_reward",
                "cost_reward",
                "phase_coverage",
                "metric_exported",
                "metric_path",
            ],
        )
        writer.writeheader()
        for record in summary.records:
            writer.writerow(
                {
                    "run_index": record.run_index,
                    "file": record.file,
                    "detection_accuracy": record.detection_accuracy,
                    "ttd": "" if record.ttd is None else f"{record.ttd:.3f}",
                    "steps": "" if record.steps is None else str(record.steps),
                    "final_reward": _format_optional_reward(record.final_reward),
                    "team_reward": _format_optional_reward(record.team_reward),
                    "ha_reward": _format_optional_reward(record.agent_rewards.get("AIServiceHASupportAgent")),
                    "app_reward": _format_optional_reward(record.agent_rewards.get("AIApplicationManagementAgent")),
                    "infra_reward": _format_optional_reward(record.agent_rewards.get("AISemiconductorInfraOpsAgent")),
                    "cost_reward": _format_optional_reward(record.agent_rewards.get("CostOptimizationAgent")),
                    "phase_coverage": record.phase_coverage,
                    "metric_exported": "yes" if record.metric_exported else "no",
                    "metric_path": record.metric_path,
                }
            )


def _mean(values: Iterable[float | int | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 3)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def _format_optional_reward(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"

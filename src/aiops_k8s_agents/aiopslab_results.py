from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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


def summarize_aiopslab_reports(runs_dir: str | Path) -> AIOpsLabSummary:
    paths = sorted(Path(runs_dir).glob("*_aiopslab_auto_detection.json"))
    records = [
        _record_from_report(index=index, path=path)
        for index, path in enumerate(paths, start=1)
    ]
    return AIOpsLabSummary(
        records=records,
        total_runs=len(records),
        correct_runs=sum(1 for record in records if record.detection_accuracy == "Correct"),
        metric_success_runs=sum(1 for record in records if record.metric_exported),
        average_ttd=_mean(record.ttd for record in records),
        average_steps=_mean(record.steps for record in records),
        average_final_reward=_mean(record.final_reward for record in records),
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
        f"- average_final_reward: {_format_optional_float(summary.average_final_reward)}",
        "",
        "## Runs",
        "",
        "| run | accuracy | TTD(s) | steps | final_reward | phases | metric | report |",
        "| ---: | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for record in summary.records:
        lines.append(
            (
                f"| {record.run_index} | {record.detection_accuracy} | "
                f"{_format_optional_float(record.ttd)} | "
                f"{record.steps if record.steps is not None else ''} | "
                f"{_format_optional_reward(record.final_reward)} | "
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
    metric_path = _extract_metric_path(decisions, aiopslab_results)
    final_reward = _extract_final_reward(decisions)
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
        final_reward=final_reward,
        phase_coverage=phase_coverage,
        metric_exported=bool(metric_path),
        metric_path=metric_path,
        final_state=str(aiopslab_results.get("final_state", "")),
    )


def _extract_metric_path(decisions: list[dict[str, Any]], aiopslab_results: dict[str, Any]) -> str:
    search_texts: list[str] = []
    search_texts.extend(str(decision.get("observation_excerpt", "")) for decision in decisions)
    search_texts.extend(str(item) for item in aiopslab_results.get("history", []))
    for text in search_texts:
        match = METRIC_PATH_PATTERN.search(text)
        if match:
            return match.group(1)
    return ""


def _extract_final_reward(decisions: list[dict[str, Any]]) -> float | None:
    for decision in reversed(decisions):
        reward = dict(decision.get("metadata", {})).get("reward_total")
        parsed = _optional_float(reward)
        if parsed is not None:
            return parsed
    return None


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
                    "final_reward": (
                        "" if record.final_reward is None else f"{record.final_reward:.2f}"
                    ),
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

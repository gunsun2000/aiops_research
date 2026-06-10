from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class FullStackRunRecord:
    scenario: str
    report_file: str
    mode: str
    controller: str
    iterations: int
    passed: int
    failed: int
    success_rate: float
    command: str
    average_reward: float | None
    initial_replicas: int | None
    final_replicas: int | None
    real_scale_verified: bool


@dataclass(frozen=True)
class FullStackSummary:
    records: list[FullStackRunRecord]
    total_scenarios: int
    successful_scenarios: int
    total_iterations: int
    total_passed: int
    total_failed: int
    average_reward: float | None
    real_scale_verified_scenarios: int


def summarize_full_stack_reports(runs_dir: str | Path) -> FullStackSummary:
    records: list[FullStackRunRecord] = []
    for path in sorted(Path(runs_dir).rglob("*.json")):
        data = _load_feedback_report(path)
        if data is None:
            continue
        records.append(_record_from_report(path, data))

    return FullStackSummary(
        records=records,
        total_scenarios=len(records),
        successful_scenarios=sum(
            1
            for record in records
            if record.iterations > 0
            and record.passed == record.iterations
            and record.failed == 0
        ),
        total_iterations=sum(record.iterations for record in records),
        total_passed=sum(record.passed for record in records),
        total_failed=sum(record.failed for record in records),
        average_reward=_mean(record.average_reward for record in records),
        real_scale_verified_scenarios=sum(
            1 for record in records if record.real_scale_verified
        ),
    )


def write_full_stack_summary_files(
    summary: FullStackSummary,
    markdown_path: str | Path,
    csv_path: str | Path,
) -> None:
    markdown_path = Path(markdown_path)
    csv_path = Path(csv_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_full_stack_markdown(summary), encoding="utf-8")
    _write_full_stack_csv(summary, csv_path)


def render_full_stack_markdown(summary: FullStackSummary) -> str:
    lines = [
        "# Full-stack 4-Agent Final Experiment Summary",
        "",
        "## Aggregate",
        "",
        f"- total_scenarios: {summary.total_scenarios}",
        f"- successful_scenarios: {summary.successful_scenarios}",
        f"- total_iterations: {summary.total_iterations}",
        f"- total_passed: {summary.total_passed}",
        f"- total_failed: {summary.total_failed}",
        f"- average_reward: {_format_optional(summary.average_reward)}",
        (
            "- real_scale_verified_scenarios: "
            f"{summary.real_scale_verified_scenarios}"
        ),
        "",
        "## Scenarios",
        "",
        (
            "| scenario | mode | controller | passed | success | reward | "
            "replicas | real control | command |"
        ),
        "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for record in summary.records:
        replicas = _replica_transition(record.initial_replicas, record.final_replicas)
        lines.append(
            (
                f"| {record.scenario} | {record.mode} | {record.controller} | "
                f"{record.passed}/{record.iterations} | "
                f"{record.success_rate * 100:.1f}% | "
                f"{_format_optional(record.average_reward)} | {replicas} | "
                f"{'yes' if record.real_scale_verified else 'no'} | "
                f"`{record.command}` |"
            )
        )
    lines.append("")
    return "\n".join(lines)


def _load_feedback_report(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("command") != "feedback-loop":
        return None
    return data


def _record_from_report(path: Path, data: dict[str, Any]) -> FullStackRunRecord:
    records = [item for item in data.get("records", []) if isinstance(item, dict)]
    rewards = [
        _optional_float(_result(item).get("metadata", {}).get("reward_total"))
        for item in records
        if isinstance(_result(item).get("metadata"), dict)
    ]
    commands = [str(_result(item).get("command", "")) for item in records]
    command = next((item for item in commands if item), "")
    initial_replicas = _snapshot_replicas(records[0].get("before")) if records else None
    final_replicas = _snapshot_replicas(records[-1].get("after")) if records else None
    mode = str(data.get("mode", ""))
    iterations = int(data.get("iterations", len(records)))
    passed = int(data.get("passed", 0))
    failed = int(data.get("failed", max(0, iterations - passed)))
    return FullStackRunRecord(
        scenario=path.parent.name,
        report_file=str(path),
        mode=mode,
        controller="autogen" if bool(data.get("autogen")) else "deterministic",
        iterations=iterations,
        passed=passed,
        failed=failed,
        success_rate=(passed / iterations) if iterations else 0.0,
        command=command,
        average_reward=_mean(rewards),
        initial_replicas=initial_replicas,
        final_replicas=final_replicas,
        real_scale_verified=(
            mode == "real"
            and initial_replicas is not None
            and final_replicas is not None
            and final_replicas > initial_replicas
            and any(bool(_result(item).get("valid")) for item in records)
        ),
    )


def _result(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result", {})
    return result if isinstance(result, dict) else {}


def _snapshot_replicas(snapshot: Any) -> int | None:
    if not isinstance(snapshot, dict):
        return None
    deployment_status = snapshot.get("deployment_status", {})
    if not isinstance(deployment_status, dict):
        return None
    return _optional_int(deployment_status.get("desired_replicas"))


def _mean(values: Iterable[float | None]) -> float | None:
    numbers = [value for value in values if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 3)


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_optional(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}"


def _replica_transition(initial: int | None, final: int | None) -> str:
    if initial is None or final is None:
        return ""
    return f"{initial} -> {final}"


def _write_full_stack_csv(summary: FullStackSummary, csv_path: Path) -> None:
    fields = [
        "scenario",
        "mode",
        "controller",
        "iterations",
        "passed",
        "failed",
        "success_rate",
        "average_reward",
        "initial_replicas",
        "final_replicas",
        "real_scale_verified",
        "command",
        "report_file",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for record in summary.records:
            writer.writerow(
                {
                    "scenario": record.scenario,
                    "mode": record.mode,
                    "controller": record.controller,
                    "iterations": record.iterations,
                    "passed": record.passed,
                    "failed": record.failed,
                    "success_rate": f"{record.success_rate:.3f}",
                    "average_reward": _format_optional(record.average_reward),
                    "initial_replicas": record.initial_replicas,
                    "final_replicas": record.final_replicas,
                    "real_scale_verified": (
                        "yes" if record.real_scale_verified else "no"
                    ),
                    "command": record.command,
                    "report_file": record.report_file,
                }
            )

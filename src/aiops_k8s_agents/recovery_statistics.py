from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from aiops_k8s_agents.recovery_experiments import (
    RECOVERY_REWARD_POLICIES,
    RecoveryOutcome,
    analyze_recovery_outcomes,
    load_recovery_outcomes,
)


def summarize_recovery_statistics(input_path: str | Path) -> dict[str, Any]:
    outcomes = load_recovery_outcomes(input_path)
    valid_outcomes = [outcome for outcome in outcomes if outcome.measurement_valid]
    scenario_action_rows = _scenario_action_statistics(valid_outcomes)
    policy_rows = _policy_reward_statistics(valid_outcomes)
    return {
        "command": "summarize-recovery-statistics",
        "valid": bool(valid_outcomes),
        "input": str(input_path),
        "input_records": len(outcomes),
        "valid_measurements": len(valid_outcomes),
        "invalid_measurements": len(outcomes) - len(valid_outcomes),
        "overall": _overall_statistics(valid_outcomes),
        "scenario_action_statistics": scenario_action_rows,
        "policy_reward_statistics": policy_rows,
    }


def write_recovery_statistics(report: dict[str, Any], output_dir: str | Path) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    (output_path / "quantitative_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        output_path / "scenario_action_statistics.csv",
        report["scenario_action_statistics"],
        [
            "scenario",
            "action",
            "runs",
            "success_rate",
            "mean_recovery_seconds",
            "mean_metric_improvement",
            "mean_availability_recovery",
            "mean_replica_delta",
            "mean_command_count",
        ],
    )
    _write_csv(
        output_path / "policy_reward_statistics.csv",
        report["policy_reward_statistics"],
        [
            "policy",
            "scenario",
            "selected_action",
            "selected_reward",
            "rank",
            "action",
            "predicted_reward",
            "observed_outcome_score",
        ],
    )
    (output_path / "quantitative_summary.md").write_text(
        _render_markdown(report),
        encoding="utf-8",
    )
    _write_bar_chart_files(
        output_path=output_path,
        stem="mean_recovery_seconds_by_action",
        title="Mean Recovery Seconds by Scenario and Action",
        rows=report["scenario_action_statistics"],
        value_key="mean_recovery_seconds",
        value_label="seconds",
        lower_is_better=True,
    )
    _write_bar_chart_files(
        output_path=output_path,
        stem="success_rate_by_action",
        title="Recovery Success Rate by Scenario and Action",
        rows=report["scenario_action_statistics"],
        value_key="success_rate",
        value_label="success rate",
        lower_is_better=False,
    )
    _write_bar_chart_files(
        output_path=output_path,
        stem="reward_by_policy",
        title="Selected Reward by Policy and Scenario",
        rows=_reward_chart_rows(report["policy_reward_statistics"]),
        value_key="selected_reward",
        value_label="selected reward",
        lower_is_better=False,
    )


def _scenario_action_statistics(outcomes: list[RecoveryOutcome]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[RecoveryOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[(outcome.scenario, outcome.action.kind.value)].append(outcome)

    rows = []
    for (scenario, action), values in sorted(grouped.items()):
        rows.append(
            {
                "scenario": scenario,
                "action": action,
                "runs": len(values),
                "success_rate": _round(_mean(float(item.recovery_success) for item in values)),
                "mean_recovery_seconds": _round(_mean(item.recovery_seconds for item in values)),
                "mean_metric_improvement": _round(_mean(item.metric_improvement for item in values)),
                "mean_availability_recovery": _round(
                    _mean(item.availability_recovery for item in values)
                ),
                "mean_replica_delta": _round(_mean(item.replica_delta for item in values)),
                "mean_command_count": _round(_mean(item.command_count for item in values)),
            }
        )
    return rows


def _policy_reward_statistics(outcomes: list[RecoveryOutcome]) -> list[dict[str, Any]]:
    if not outcomes:
        return []
    analysis = analyze_recovery_outcomes(outcomes)
    rows: list[dict[str, Any]] = []
    for policy in RECOVERY_REWARD_POLICIES:
        for scenario, result in analysis["policies"][policy].items():
            selected_action = result["selected_action"]
            selected_reward = next(
                item["predicted_reward"]
                for item in result["ranking"]
                if item["action"] == selected_action
            )
            for item in result["ranking"]:
                rows.append(
                    {
                        "policy": policy,
                        "scenario": scenario,
                        "selected_action": selected_action,
                        "selected_reward": selected_reward,
                        "rank": item["rank"],
                        "action": item["action"],
                        "predicted_reward": item["predicted_reward"],
                        "observed_outcome_score": item["observed_outcome_score"],
                    }
                )
    return rows


def _overall_statistics(outcomes: list[RecoveryOutcome]) -> dict[str, Any]:
    if not outcomes:
        return {
            "success_rate": 0.0,
            "mean_recovery_seconds": 0.0,
            "mean_metric_improvement": 0.0,
            "mean_availability_recovery": 0.0,
        }
    return {
        "success_rate": _round(_mean(float(item.recovery_success) for item in outcomes)),
        "mean_recovery_seconds": _round(_mean(item.recovery_seconds for item in outcomes)),
        "mean_metric_improvement": _round(_mean(item.metric_improvement for item in outcomes)),
        "mean_availability_recovery": _round(
            _mean(item.availability_recovery for item in outcomes)
        ),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(report: dict[str, Any]) -> str:
    overall = report["overall"]
    lines = [
        "# Recovery Quantitative Statistics",
        "",
        f"- input_records: {report['input_records']}",
        f"- valid_measurements: {report['valid_measurements']}",
        f"- invalid_measurements: {report['invalid_measurements']}",
        f"- overall_success_rate: {overall['success_rate']:.3f}",
        f"- mean_recovery_seconds: {overall['mean_recovery_seconds']:.3f}",
        f"- mean_metric_improvement: {overall['mean_metric_improvement']:.3f}",
        "",
        "## Scenario / Action Statistics",
        "",
        "| scenario | action | runs | success rate | mean recovery seconds | mean metric improvement |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report["scenario_action_statistics"]:
        lines.append(
            "| {scenario} | {action} | {runs} | {success_rate:.3f} | "
            "{mean_recovery_seconds:.3f} | {mean_metric_improvement:.3f} |".format(
                **row
            )
        )

    lines.extend(
        [
            "",
            "## Reward Policy Selection Summary",
            "",
            "| policy | scenario | selected action | selected reward |",
            "| --- | --- | --- | ---: |",
        ]
    )
    seen = set()
    for row in report["policy_reward_statistics"]:
        key = (row["policy"], row["scenario"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            "| {policy} | {scenario} | {selected_action} | {selected_reward:.3f} |".format(
                **row
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_bar_svg(
    *,
    title: str,
    rows: list[dict[str, Any]],
    value_key: str,
    value_label: str,
    lower_is_better: bool,
) -> str:
    width = 1180
    row_height = 30
    top = 64
    left = 320
    chart_width = 760
    height = max(240, top + len(rows) * row_height + 50)
    max_value = max([float(row[value_key]) for row in rows] + [1.0])
    palette = {
        "observe_only": "#2f6fdd",
        "rollout_restart": "#12805c",
        "scale_out": "#b7791f",
    }

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="24" y="34" font-family="Arial, sans-serif" font-size="22" font-weight="700" fill="#111">{_escape(title)}</text>',
        f'<text x="{left}" y="54" font-family="Arial, sans-serif" font-size="12" fill="#444">{_escape(value_label)}</text>',
    ]
    for index, row in enumerate(rows):
        y = top + index * row_height
        label = f"{row['scenario']} / {row['action']}"
        value = float(row[value_key])
        bar_width = 0 if max_value == 0 else int((value / max_value) * chart_width)
        color = palette.get(str(row["action"]), "#4a5568")
        suffix = " lower is better" if lower_is_better else ""
        parts.extend(
            [
                f'<text x="24" y="{y + 18}" font-family="Arial, sans-serif" font-size="13" fill="#222">{_escape(label)}</text>',
                f'<rect x="{left}" y="{y + 4}" width="{bar_width}" height="18" fill="{color}"/>',
                f'<text x="{left + bar_width + 8}" y="{y + 18}" font-family="Arial, sans-serif" font-size="13" fill="#222">{value:.3f}</text>',
            ]
        )
    parts.append(
        f'<text x="24" y="{height - 18}" font-family="Arial, sans-serif" font-size="12" fill="#555">Generated from recovery experiment outcomes.{suffix}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _write_bar_chart_files(
    *,
    output_path: Path,
    stem: str,
    title: str,
    rows: list[dict[str, Any]],
    value_key: str,
    value_label: str,
    lower_is_better: bool,
) -> None:
    (output_path / f"{stem}.svg").write_text(
        _render_bar_svg(
            title=title,
            rows=rows,
            value_key=value_key,
            value_label=value_label,
            lower_is_better=lower_is_better,
        ),
        encoding="utf-8",
    )
    _write_bar_png(
        path=output_path / f"{stem}.png",
        title=title,
        rows=rows,
        value_key=value_key,
        value_label=value_label,
        lower_is_better=lower_is_better,
    )


def _write_bar_png(
    *,
    path: Path,
    title: str,
    rows: list[dict[str, Any]],
    value_key: str,
    value_label: str,
    lower_is_better: bool,
) -> None:
    from PIL import Image, ImageDraw

    width = 1400
    row_height = 38
    top = 90
    left = 410
    chart_width = 860
    height = max(320, top + len(rows) * row_height + 72)
    max_value = max([float(row[value_key]) for row in rows] + [1.0])
    palette = {
        "observe_only": "#2f6fdd",
        "rollout_restart": "#12805c",
        "scale_out": "#b7791f",
    }

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = _load_png_font(size=26, bold=True)
    text_font = _load_png_font(size=16)
    small_font = _load_png_font(size=14)

    draw.text((24, 24), str(title), fill="#111111", font=title_font)
    draw.text((left, 62), str(value_label), fill="#444444", font=small_font)

    for index, row in enumerate(rows):
        y = top + index * row_height
        label = f"{row['scenario']} / {row['action']}"
        value = float(row[value_key])
        bar_width = 0 if max_value == 0 else int((value / max_value) * chart_width)
        color = palette.get(str(row["action"]), "#4a5568")
        draw.text((24, y + 9), label, fill="#222222", font=text_font)
        if bar_width > 0:
            draw.rectangle(
                (left, y + 7, left + bar_width, y + 28),
                fill=color,
            )
        draw.text(
            (left + bar_width + 10, y + 9),
            f"{value:.3f}",
            fill="#222222",
            font=text_font,
        )

    suffix = " lower is better" if lower_is_better else ""
    draw.text(
        (24, height - 34),
        f"Generated from recovery experiment outcomes.{suffix}",
        fill="#555555",
        font=small_font,
    )
    image.save(path, format="PNG")


def _load_png_font(*, size: int, bold: bool = False) -> Any:
    from PIL import ImageFont

    candidates = (
        ["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"]
        if bold
        else ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf"]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _reward_chart_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_rows = [row for row in rows if int(row["rank"]) == 1]
    return [
        {
            "scenario": row["policy"],
            "action": row["scenario"],
            "selected_reward": row["selected_reward"],
        }
        for row in selected_rows
    ]


def _mean(values: Iterable[float]) -> float:
    data = list(values)
    if not data:
        return 0.0
    return sum(data) / len(data)


def _round(value: float) -> float:
    return round(float(value), 6)


def _escape(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Protocol

from .mutual_supervision_models import to_serializable


EVENT_STREAMS = {
    "evidence",
    "initial_decisions",
    "peer_reviews",
    "negotiation_rounds",
    "safety_validations",
    "executed_actions",
    "post_execution_reviews",
}


class ResearchEventSink(Protocol):
    def append(self, stream: str, event: Any) -> None: ...

    def finalize(self, report: dict[str, Any]) -> dict[str, str]: ...


class InMemoryResearchEventStore:
    def __init__(self) -> None:
        self.events: dict[str, list[Any]] = defaultdict(list)
        self.final_report: dict[str, Any] = {}

    def append(self, stream: str, event: Any) -> None:
        _validate_stream(stream)
        self.events[stream].append(to_serializable(event))

    def finalize(self, report: dict[str, Any]) -> dict[str, str]:
        self.final_report = to_serializable(report)
        return {}


class JsonlResearchEventStore:
    def __init__(
        self,
        root_dir: str | Path,
        experiment_id: str,
        experiment_config: dict[str, Any] | None = None,
    ) -> None:
        self.run_dir = Path(root_dir) / experiment_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.paths: dict[str, str] = {}
        for stream in sorted(EVENT_STREAMS):
            path = self.run_dir / f"{stream}.jsonl"
            path.touch(exist_ok=True)
            self.paths[stream] = str(path)
        _write_json(
            self.run_dir / "experiment_config.json",
            experiment_config or {},
        )

    def append(self, stream: str, event: Any) -> None:
        _validate_stream(stream)
        path = self.run_dir / f"{stream}.jsonl"
        with path.open("a", encoding="utf-8") as output:
            output.write(
                json.dumps(
                    to_serializable(event),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
        self.paths[stream] = str(path)

    def finalize(self, report: dict[str, Any]) -> dict[str, str]:
        serializable_report = to_serializable(report)
        json_path = self.run_dir / "final_report.json"
        markdown_path = self.run_dir / "final_report.md"
        statistics_path = self.run_dir / "statistics.csv"

        _write_json(json_path, serializable_report)
        markdown_path.write_text(
            _render_markdown_summary(serializable_report),
            encoding="utf-8",
        )
        _write_statistics_csv(statistics_path, serializable_report)

        self.paths.update(
            {
                "final_report_json": str(json_path),
                "final_report_md": str(markdown_path),
                "statistics_csv": str(statistics_path),
            }
        )
        return dict(self.paths)


def _validate_stream(stream: str) -> None:
    if stream not in EVENT_STREAMS:
        allowed = ", ".join(sorted(EVENT_STREAMS))
        raise ValueError(f"unknown event stream {stream!r}; expected one of: {allowed}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            to_serializable(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _summary_row(report: dict[str, Any]) -> dict[str, Any]:
    negotiation = report.get("negotiation") or {}
    reviews = report.get("peer_reviews") or []
    selected_action = report.get("selected_action") or {}
    post_reviews = report.get("post_execution_reviews") or []
    verdict_counts = {
        verdict: sum(1 for review in reviews if review.get("verdict") == verdict)
        for verdict in ("approve", "revise", "veto", "abstain")
    }
    post_approved = sum(
        1 for review in post_reviews if review.get("approved") is True
    )
    post_approval_rate = (
        post_approved / len(post_reviews) if post_reviews else 0.0
    )
    return {
        "run_id": report.get("run_id", ""),
        "policy_version": report.get("policy_version", ""),
        "final_status": report.get("final_status", ""),
        "valid": report.get("valid", False),
        "consensus": negotiation.get("consensus", ""),
        "round_count": negotiation.get("round_count", 0),
        "approve_count": verdict_counts["approve"],
        "revise_count": verdict_counts["revise"],
        "veto_count": verdict_counts["veto"],
        "abstain_count": verdict_counts["abstain"],
        "selected_action": selected_action.get("kind", ""),
        "selected_replicas": selected_action.get("replicas", ""),
        "post_review_approval_rate": f"{post_approval_rate:.3f}",
        "human_review_required": report.get(
            "human_review_required", False
        ),
    }


def _write_statistics_csv(
    path: Path,
    report: dict[str, Any],
) -> None:
    row = _summary_row(report)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def _render_markdown_summary(report: dict[str, Any]) -> str:
    row = _summary_row(report)
    return "\n".join(
        [
            "# Mutual-Supervision AIOps Experiment",
            "",
            f"- run_id: `{row['run_id']}`",
            f"- policy_version: `{row['policy_version']}`",
            f"- final_status: `{row['final_status']}`",
            f"- valid: `{str(row['valid']).lower()}`",
            f"- consensus: `{row['consensus']}`",
            f"- negotiation_rounds: `{row['round_count']}`",
            f"- selected_action: `{row['selected_action']}`",
            f"- selected_replicas: `{row['selected_replicas']}`",
            f"- post_review_approval_rate: `{row['post_review_approval_rate']}`",
            (
                "- human_review_required: "
                f"`{str(row['human_review_required']).lower()}`"
            ),
            "",
            "## Peer Review Verdicts",
            "",
            "| approve | revise | veto | abstain |",
            "| ---: | ---: | ---: | ---: |",
            (
                f"| {row['approve_count']} | {row['revise_count']} | "
                f"{row['veto_count']} | {row['abstain_count']} |"
            ),
            "",
        ]
    )

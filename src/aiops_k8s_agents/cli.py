from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from aiops_k8s_agents.agents import AIMCMPCoordinator
from aiops_k8s_agents.autogen_groupchat import (
    AutoGenDecisionError,
    AutoGenGroupChatCoordinator,
    AutoGenRoundRobinDecisionProvider,
    create_openai_model_client,
)
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.full_stack_experiments import (
    load_full_stack_experiment_plan,
    plan_to_dict,
)
from aiops_k8s_agents.full_stack_results import (
    summarize_full_stack_reports,
    write_full_stack_summary_files,
)
from aiops_k8s_agents.aiopslab_results import (
    summarize_aiopslab_reports,
    write_aiopslab_summary_files,
)
from aiops_k8s_agents.kubernetes_status import collect_kubernetes_snapshot
from aiops_k8s_agents.models import AlertEvent, CommandResult
from aiops_k8s_agents.prometheus import (
    PrometheusAdapter,
    PrometheusAdapterError,
    PrometheusMetricConfig,
    load_prometheus_response,
    prometheus_result_to_alert_event,
)
from aiops_k8s_agents.validator import CommandValidationError, CommandValidator

DEFAULT_OPENAI_MODEL = os.environ.get("AIOPS_OPENAI_MODEL", "gpt-5.5")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiops-k8s-agents",
        description="Run the AIOps Kubernetes action coordinator.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run one alert through the deterministic coordinator.",
    )
    _add_alert_arguments(run_parser)

    autogen_parser = subparsers.add_parser(
        "autogen-run",
        help="Run one alert through AutoGen RoundRobinGroupChat.",
    )
    _add_alert_arguments(autogen_parser)
    autogen_parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL)
    _add_autogen_transcript_argument(autogen_parser)

    prometheus_parser = subparsers.add_parser(
        "prometheus-run",
        help="Read one Prometheus query result and run it through the coordinator.",
    )
    prometheus_parser.add_argument("--mode", choices=[mode.value for mode in ExecutionMode], default="mock")
    prometheus_parser.add_argument("--prometheus-url", default="")
    prometheus_parser.add_argument("--mock-response-file", default="")
    prometheus_parser.add_argument("--query", required=True)
    prometheus_parser.add_argument("--metric", required=True)
    prometheus_parser.add_argument("--threshold", required=True, type=float)
    prometheus_parser.add_argument("--default-namespace", required=True)
    prometheus_parser.add_argument("--default-service", required=True)
    prometheus_parser.add_argument("--allowed-namespace", action="append", required=True)
    prometheus_parser.add_argument("--allowed-deployment", action="append", required=True)
    prometheus_parser.add_argument("--min-replicas", type=int, default=1)
    prometheus_parser.add_argument("--max-replicas", type=int, default=5)

    autogen_prometheus_parser = subparsers.add_parser(
        "autogen-prometheus-run",
        help="Read one Prometheus query result and run it through AutoGen GroupChat.",
    )
    _add_prometheus_arguments(autogen_prometheus_parser)
    autogen_prometheus_parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL)
    _add_autogen_transcript_argument(autogen_prometheus_parser)

    feedback_loop_parser = subparsers.add_parser(
        "feedback-loop",
        help="Repeatedly read Prometheus, run the 4-agent controller, and save a research report.",
    )
    _add_prometheus_arguments(feedback_loop_parser)
    feedback_loop_parser.add_argument("--iterations", type=int, default=3)
    feedback_loop_parser.add_argument("--interval-seconds", type=float, default=10.0)
    feedback_loop_parser.add_argument(
        "--autogen",
        action="store_true",
        help="Use AutoGen GroupChat for each loop iteration.",
    )
    feedback_loop_parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL)
    feedback_loop_parser.add_argument(
        "--no-kubernetes-snapshot",
        action="store_true",
        help="Skip before/after kubectl deployment and pod snapshots.",
    )
    _add_autogen_transcript_argument(feedback_loop_parser)

    aiopslab_summary_parser = subparsers.add_parser(
        "summarize-aiopslab-runs",
        help="Summarize saved AIOpsLab auto-detection reports into Markdown and CSV.",
    )
    aiopslab_summary_parser.add_argument("--runs-dir", default="runs")
    aiopslab_summary_parser.add_argument(
        "--output-md",
        default="",
        help="Markdown summary path. Defaults to <runs-dir>/aiopslab_detection_summary.md.",
    )
    aiopslab_summary_parser.add_argument(
        "--output-csv",
        default="",
        help="CSV summary path. Defaults to <runs-dir>/aiopslab_detection_summary.csv.",
    )

    full_stack_parser = subparsers.add_parser(
        "list-full-stack-experiments",
        help="Print the fixed full-stack environment and controlled experiment variables.",
    )
    full_stack_parser.add_argument(
        "--config",
        default="config/full_stack_experiments.json",
        help="Full-stack experiment matrix JSON path.",
    )
    _add_result_logging_argument(full_stack_parser)

    full_stack_summary_parser = subparsers.add_parser(
        "summarize-full-stack-runs",
        help="Summarize full-stack feedback-loop reports into Markdown and CSV.",
    )
    full_stack_summary_parser.add_argument("--runs-dir", required=True)
    full_stack_summary_parser.add_argument("--output-md", default="")
    full_stack_summary_parser.add_argument("--output-csv", default="")

    return parser


def _add_alert_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=[mode.value for mode in ExecutionMode], default="mock")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--service", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--value", required=True, type=float)
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--message", default="")
    parser.add_argument("--allowed-namespace", action="append", required=True)
    parser.add_argument("--allowed-deployment", action="append", required=True)
    parser.add_argument("--min-replicas", type=int, default=1)
    parser.add_argument("--max-replicas", type=int, default=5)
    _add_result_logging_argument(parser)


def _add_prometheus_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=[mode.value for mode in ExecutionMode], default="mock")
    parser.add_argument("--prometheus-url", default="")
    parser.add_argument("--mock-response-file", default="")
    parser.add_argument("--query", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--threshold", required=True, type=float)
    parser.add_argument("--default-namespace", required=True)
    parser.add_argument("--default-service", required=True)
    parser.add_argument("--allowed-namespace", action="append", required=True)
    parser.add_argument("--allowed-deployment", action="append", required=True)
    parser.add_argument("--min-replicas", type=int, default=1)
    parser.add_argument("--max-replicas", type=int, default=5)
    _add_result_logging_argument(parser)


def _add_result_logging_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--save-result-dir",
        default="",
        help="Optional directory where the final CommandResult JSON is saved.",
    )


def _add_autogen_transcript_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--show-transcript",
        action="store_true",
        help="Include a readable AutoGen agent transcript in metadata.transcript.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        result = _run_alert(args)
        _emit_result(args, result)
        return 0 if result.valid else 2

    if args.command == "autogen-run":
        result = asyncio.run(run_autogen_groupchat(args))
        _emit_result(args, result)
        return 0 if result.valid else 2

    if args.command == "prometheus-run":
        result = run_prometheus_alert(args)
        _emit_result(args, result)
        return 0 if result.valid else 2

    if args.command == "autogen-prometheus-run":
        result = asyncio.run(run_autogen_prometheus_alert(args))
        _emit_result(args, result)
        return 0 if result.valid else 2

    if args.command == "feedback-loop":
        report = run_feedback_loop(args)
        _emit_json_report(args, report)
        return 0 if report["failed"] == 0 else 2

    if args.command == "summarize-aiopslab-runs":
        report = summarize_aiopslab_runs(args)
        _emit_json_report(args, report)
        return 0

    if args.command == "list-full-stack-experiments":
        report = list_full_stack_experiments(args)
        _emit_json_report(args, report)
        return 0

    if args.command == "summarize-full-stack-runs":
        report = summarize_full_stack_runs(args)
        _emit_json_report(args, report)
        return 0 if report["total_failed"] == 0 else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


def list_full_stack_experiments(args: argparse.Namespace) -> dict[str, Any]:
    plan = load_full_stack_experiment_plan(Path(args.config))
    return plan_to_dict(plan)


def summarize_aiopslab_runs(args: argparse.Namespace) -> dict[str, Any]:
    runs_dir = Path(args.runs_dir)
    output_md = Path(args.output_md) if args.output_md else runs_dir / "aiopslab_detection_summary.md"
    output_csv = (
        Path(args.output_csv)
        if args.output_csv
        else runs_dir / "aiopslab_detection_summary.csv"
    )
    summary = summarize_aiopslab_reports(runs_dir)
    write_aiopslab_summary_files(
        summary,
        markdown_path=output_md,
        csv_path=output_csv,
    )
    return {
        "command": "summarize-aiopslab-runs",
        "runs_dir": str(runs_dir),
        "output_md": str(output_md),
        "output_csv": str(output_csv),
        "total_runs": summary.total_runs,
        "correct_runs": summary.correct_runs,
        "metric_success_runs": summary.metric_success_runs,
        "average_ttd": summary.average_ttd,
        "average_steps": summary.average_steps,
        "average_final_reward": summary.average_final_reward,
    }


def summarize_full_stack_runs(args: argparse.Namespace) -> dict[str, Any]:
    runs_dir = Path(args.runs_dir)
    output_md = Path(args.output_md) if args.output_md else runs_dir / "final_summary.md"
    output_csv = Path(args.output_csv) if args.output_csv else runs_dir / "final_summary.csv"
    summary = summarize_full_stack_reports(runs_dir)
    write_full_stack_summary_files(summary, output_md, output_csv)
    return {
        "command": "summarize-full-stack-runs",
        "runs_dir": str(runs_dir),
        "output_md": str(output_md),
        "output_csv": str(output_csv),
        "total_scenarios": summary.total_scenarios,
        "successful_scenarios": summary.successful_scenarios,
        "total_iterations": summary.total_iterations,
        "total_passed": summary.total_passed,
        "total_failed": summary.total_failed,
        "average_reward": summary.average_reward,
        "real_scale_verified_scenarios": summary.real_scale_verified_scenarios,
    }


def run_feedback_loop(args: argparse.Namespace) -> dict[str, Any]:
    if args.iterations < 1:
        raise ValueError("--iterations must be at least 1")
    records: list[dict[str, Any]] = []

    for index in range(args.iterations):
        before = _snapshot_from_args(args)
        result = _run_feedback_iteration(args)
        after = _snapshot_from_args(args)
        records.append(
            {
                "iteration": index + 1,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "before": before,
                "result": asdict(result),
                "after": after,
            }
        )
        if index < args.iterations - 1:
            time.sleep(args.interval_seconds)

    failed = sum(1 for record in records if not record["result"]["valid"])
    return {
        "command": "feedback-loop",
        "mode": args.mode,
        "iterations": args.iterations,
        "failed": failed,
        "passed": args.iterations - failed,
        "input_source": "prometheus",
        "autogen": bool(args.autogen),
        "records": records,
    }


def _run_feedback_iteration(args: argparse.Namespace) -> CommandResult:
    if args.autogen:
        return asyncio.run(run_autogen_prometheus_alert(args))
    return run_prometheus_alert(args)


def _snapshot_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.no_kubernetes_snapshot:
        return None
    return collect_kubernetes_snapshot(
        namespace=args.default_namespace,
        deployment=args.default_service,
    )


def _run_alert(args: argparse.Namespace) -> CommandResult:
    validator = _validator_from_args(args)
    alert = _alert_from_args(args)
    return _run_alert_with_validator(args, alert, validator)


def _run_alert_with_validator(
    args: argparse.Namespace,
    alert: AlertEvent,
    validator: CommandValidator,
) -> CommandResult:
    coordinator = AIMCMPCoordinator(
        validator=validator,
        mode=ExecutionMode(args.mode),
    )
    try:
        return coordinator.run(alert)
    except CommandValidationError as exc:
        return _error_result(args.mode, str(exc), {"coordinator": "AI-MCMP"})


async def run_autogen_groupchat(args: argparse.Namespace) -> CommandResult:
    validator = _validator_from_args(args)
    alert = _alert_from_args(args)

    try:
        model_client = create_openai_model_client(args.model)
    except Exception as exc:
        return _error_result(
            args.mode,
            str(exc),
            {"coordinator": "AI-MCMP", "autogen": "groupchat"},
        )

    try:
        provider = AutoGenRoundRobinDecisionProvider(model_client=model_client)
        coordinator = AutoGenGroupChatCoordinator(
            validator=validator,
            mode=ExecutionMode(args.mode),
            decision_provider=provider,
            include_transcript=args.show_transcript,
        )
        return await coordinator.run(alert)
    except (AutoGenDecisionError, CommandValidationError, RuntimeError, ValueError) as exc:
        return _error_result(
            args.mode,
            str(exc),
            {"coordinator": "AI-MCMP", "autogen": "groupchat"},
        )
    finally:
        close = getattr(model_client, "close", None)
        if close is not None:
            closed = close()
            if inspect.isawaitable(closed):
                await closed


async def run_autogen_prometheus_alert(args: argparse.Namespace) -> CommandResult:
    try:
        alert = _prometheus_alert_from_args(args)
    except Exception as exc:
        return _error_result(
            args.mode,
            str(exc),
            {
                "coordinator": "AI-MCMP",
                "autogen": "groupchat",
                "input_source": "prometheus",
            },
        )

    validator = _validator_from_args(args)

    try:
        model_client = create_openai_model_client(args.model)
    except Exception as exc:
        return _error_result(
            args.mode,
            str(exc),
            {
                "coordinator": "AI-MCMP",
                "autogen": "groupchat",
                "input_source": "prometheus",
            },
        )

    try:
        provider = AutoGenRoundRobinDecisionProvider(model_client=model_client)
        coordinator = AutoGenGroupChatCoordinator(
            validator=validator,
            mode=ExecutionMode(args.mode),
            decision_provider=provider,
            include_transcript=args.show_transcript,
        )
        result = await coordinator.run(alert)
        return replace(
            result,
            metadata={**result.metadata, "input_source": "prometheus"},
        )
    except (AutoGenDecisionError, CommandValidationError, RuntimeError, ValueError) as exc:
        return _error_result(
            args.mode,
            str(exc),
            {
                "coordinator": "AI-MCMP",
                "autogen": "groupchat",
                "input_source": "prometheus",
            },
        )
    finally:
        close = getattr(model_client, "close", None)
        if close is not None:
            closed = close()
            if inspect.isawaitable(closed):
                await closed


def run_prometheus_alert(args: argparse.Namespace) -> CommandResult:
    try:
        alert = _prometheus_alert_from_args(args)
    except Exception as exc:
        return _error_result(
            args.mode,
            str(exc),
            {"coordinator": "AI-MCMP", "input_source": "prometheus"},
        )

    validator = _validator_from_args(args)
    result = _run_alert_with_validator(args, alert, validator)
    return replace(result, metadata={**result.metadata, "input_source": "prometheus"})


def _prometheus_alert_from_args(args: argparse.Namespace) -> AlertEvent:
    config = PrometheusMetricConfig(
        query=args.query,
        metric=args.metric,
        threshold=args.threshold,
        default_namespace=args.default_namespace,
        default_service=args.default_service,
    )
    if args.mock_response_file:
        return prometheus_result_to_alert_event(
            load_prometheus_response(args.mock_response_file),
            config,
        )
    if not args.prometheus_url:
        raise PrometheusAdapterError("--prometheus-url or --mock-response-file is required")
    return PrometheusAdapter(args.prometheus_url).query_alert(config)


def _validator_from_args(args: argparse.Namespace) -> CommandValidator:
    return CommandValidator(
        allowed_namespaces=set(args.allowed_namespace),
        allowed_deployments=set(args.allowed_deployment),
        min_replicas=args.min_replicas,
        max_replicas=args.max_replicas,
    )


def _alert_from_args(args: argparse.Namespace) -> AlertEvent:
    return AlertEvent(
        namespace=args.namespace,
        service=args.service,
        metric=args.metric,
        value=args.value,
        threshold=args.threshold,
        message=args.message
        or f"Prometheus alert: {args.service} {args.metric} is {args.value}",
    )


def _error_result(mode: str, error: str, metadata: dict[str, str]) -> CommandResult:
    merged_metadata = {"consensus": "rejected", **metadata}
    return CommandResult(
        command="",
        mode=mode,
        valid=False,
        stdout="",
        stderr=error,
        metadata=merged_metadata,
    )


def _emit_result(args: argparse.Namespace, result: CommandResult) -> None:
    data = asdict(result)
    _emit_json_report(args, data, mode=str(result.mode))


def _emit_json_report(
    args: argparse.Namespace,
    data: dict,
    mode: str = "report",
) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text)

    save_result_dir = getattr(args, "save_result_dir", "")
    if not save_result_dir:
        return

    output_dir = Path(save_result_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    command_name = str(args.command).replace("-", "_")
    normalized_mode = mode.replace("-", "_")
    output_path = output_dir / f"{timestamp}_{command_name}_{normalized_mode}.json"
    output_path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

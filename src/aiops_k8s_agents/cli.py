from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Sequence

from aiops_k8s_agents.agents import AIMCMPCoordinator
from aiops_k8s_agents.autogen_groupchat import (
    AutoGenDecisionError,
    AutoGenGroupChatCoordinator,
    AutoGenRoundRobinDecisionProvider,
    create_openai_model_client,
)
from aiops_k8s_agents.executor import ExecutionMode
from aiops_k8s_agents.models import AlertEvent, CommandResult
from aiops_k8s_agents.prometheus import (
    PrometheusAdapter,
    PrometheusAdapterError,
    PrometheusMetricConfig,
    load_prometheus_response,
    prometheus_result_to_alert_event,
)
from aiops_k8s_agents.validator import CommandValidationError, CommandValidator


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
    autogen_parser.add_argument("--model", default="gpt-4o-mini")

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
    autogen_prometheus_parser.add_argument("--model", default="gpt-4o-mini")
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

    parser.error(f"unsupported command: {args.command}")
    return 2


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
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text)

    save_result_dir = getattr(args, "save_result_dir", "")
    if not save_result_dir:
        return

    output_dir = Path(save_result_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    command_name = str(args.command).replace("-", "_")
    mode = str(result.mode).replace("-", "_")
    output_path = output_dir / f"{timestamp}_{command_name}_{mode}.json"
    output_path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

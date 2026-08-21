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
from aiops_k8s_agents.agent_registry import (
    AgentProfile,
    AgentRegistry,
    AgentRegistryError,
    load_agent_registry,
    save_agent_registry,
)
from aiops_k8s_agents.autogen_groupchat import (
    AUTOGEN_RUNTIME,
    AutoGenDecisionError,
    AutoGenGroupChatCoordinator,
    AutoGenRoundRobinDecisionProvider,
    DecisionProvider,
    build_autogen_agent_adapter_registry,
    create_openai_model_client,
)
from aiops_k8s_agents.autonomous import AutonomousAIOpsCoordinator
from aiops_k8s_agents.evidence import (
    EvidenceSnapshot,
    FakeEvidenceProvider,
    KubernetesEvidenceProvider,
)
from aiops_k8s_agents.executor import (
    ExecutionBackend,
    ExecutionMode,
    KubernetesExecutor,
)
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
from aiops_k8s_agents.action_policy import (
    ContextualBanditPolicy,
    PolicyContext,
    load_policy_samples,
    write_policy_samples,
)
from aiops_k8s_agents.kubernetes_status import collect_kubernetes_snapshot
from aiops_k8s_agents.models import (
    AlertEvent,
    CommandResult,
    RecoveryAction,
    RecoveryActionKind,
)
from aiops_k8s_agents.partition_models import PartitionContractError
from aiops_k8s_agents.partition_learning import (
    build_partition_ranking_dataset,
    evaluate_partition_ranker,
    load_partition_ranking_dataset,
    train_partition_ranker,
)
from aiops_k8s_agents.partition_ranker_repository import PartitionRankerRepository
from aiops_k8s_agents.partition_repository import PartitionPlanRepository
from aiops_k8s_agents.partition_service import (
    run_partition_feedback,
    run_partition_planning,
)
from aiops_k8s_agents.mutual_supervision import (
    MutualSupervisionCoordinator,
    mutual_supervision_controller_name,
    resolve_mutual_supervision_protocol,
)
from aiops_k8s_agents.mutual_supervision_policy import (
    load_mutual_supervision_policy,
)
from aiops_k8s_agents.recovery_experiments import (
    analyze_recovery_outcomes,
    load_recovery_outcomes,
    write_recovery_analysis,
)
from aiops_k8s_agents.recovery_statistics import (
    summarize_recovery_statistics,
    write_recovery_statistics,
)
from aiops_k8s_agents.recovery_runner import (
    load_recovery_experiment_config,
    run_recovery_matrix,
)
from aiops_k8s_agents.recovery_monitor import (
    FakeRecoveryMonitor,
    KubernetesSnapshotRecoveryMonitor,
)
from aiops_k8s_agents.research_event_store import JsonlResearchEventStore
from aiops_k8s_agents.research_protocol import (
    ResearchProtocolProfile,
    load_protocol_profiles,
)
from aiops_k8s_agents.prometheus import (
    PrometheusAdapter,
    PrometheusAdapterError,
    PrometheusMetricConfig,
    load_prometheus_response,
    prometheus_result_to_alert_event,
)
from aiops_k8s_agents.validator import CommandValidationError, CommandValidator

DEFAULT_OPENAI_MODEL = os.environ.get("AIOPS_OPENAI_MODEL", "gpt-5.5")
DEFAULT_AGENT_REGISTRY = "config/agent_registry.json"
PROTOCOL_PROFILE_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "config" / "protocol_profiles"
)


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
    _add_guard_backend_argument(prometheus_parser)
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

    recovery_action_parser = subparsers.add_parser(
        "execute-recovery-action",
        help="Validate and execute one bounded recovery action.",
    )
    recovery_action_parser.add_argument(
        "--mode", choices=[mode.value for mode in ExecutionMode], default="mock"
    )
    _add_guard_backend_argument(recovery_action_parser)
    recovery_action_parser.add_argument(
        "--action",
        choices=[kind.value for kind in RecoveryActionKind],
        required=True,
    )
    recovery_action_parser.add_argument("--namespace", required=True)
    recovery_action_parser.add_argument("--deployment", required=True)
    recovery_action_parser.add_argument("--replicas", type=int)
    recovery_action_parser.add_argument("--reason", default="recovery experiment")
    recovery_action_parser.add_argument(
        "--allowed-namespace", action="append", required=True
    )
    recovery_action_parser.add_argument(
        "--allowed-deployment", action="append", required=True
    )
    recovery_action_parser.add_argument("--min-replicas", type=int, default=1)
    recovery_action_parser.add_argument("--max-replicas", type=int, default=5)
    _add_result_logging_argument(recovery_action_parser)

    recovery_score_parser = subparsers.add_parser(
        "score-recovery-experiments",
        help="Rank measured recovery actions under all reward policies.",
    )
    recovery_score_parser.add_argument("--input", required=True)
    recovery_score_parser.add_argument("--output-dir", required=True)

    recovery_statistics_parser = subparsers.add_parser(
        "summarize-recovery-statistics",
        help="Create quantitative tables plus SVG/PNG charts from recovery outcomes.",
    )
    recovery_statistics_parser.add_argument("--input", required=True)
    recovery_statistics_parser.add_argument("--output-dir", required=True)

    action_policy_dataset_parser = subparsers.add_parser(
        "build-action-policy-dataset",
        help="Convert recovery outcome JSONL into advisory action-policy samples.",
    )
    action_policy_dataset_parser.add_argument("--input", required=True)
    action_policy_dataset_parser.add_argument("--output", required=True)

    action_policy_recommend_parser = subparsers.add_parser(
        "recommend-action",
        help="Recommend one existing bounded action with baseline or learned policy.",
    )
    action_policy_recommend_parser.add_argument(
        "--mode", choices=["baseline", "learned"], default="baseline"
    )
    action_policy_recommend_parser.add_argument("--samples", default="")
    action_policy_recommend_parser.add_argument("--scenario", required=True)
    action_policy_recommend_parser.add_argument("--metric", default="")
    action_policy_recommend_parser.add_argument("--cause", default="")
    action_policy_recommend_parser.add_argument("--severity", default="")

    recovery_matrix_parser = subparsers.add_parser(
        "run-recovery-experiments",
        help="Run the real Chaos Mesh fault/action treatment matrix.",
    )
    recovery_matrix_parser.add_argument(
        "--config",
        default="config/recovery_action_experiments.json",
    )
    recovery_matrix_parser.add_argument(
        "--mode",
        choices=[mode.value for mode in ExecutionMode],
        default="real",
    )
    _add_guard_backend_argument(recovery_matrix_parser)
    recovery_matrix_parser.add_argument("--repetitions", type=int, default=1)
    recovery_matrix_parser.add_argument(
        "--prometheus-url",
        default="http://127.0.0.1:9090",
    )
    recovery_matrix_parser.add_argument("--output", required=True)

    autonomous_parser = subparsers.add_parser(
        "autonomous-run",
        help=(
            "Run the safety-bounded closed-loop autonomous 4-Agent flow: "
            "evidence collection, diagnosis, candidate planning, validation, "
            "execution, recovery monitoring, and bounded replanning."
        ),
    )
    autonomous_parser.add_argument(
        "--mode", choices=[mode.value for mode in ExecutionMode], default="mock"
    )
    _add_guard_backend_argument(autonomous_parser)
    autonomous_parser.add_argument(
        "--evidence-source",
        choices=["fake", "kubernetes"],
        default="fake",
    )
    autonomous_parser.add_argument("--namespace", required=True)
    autonomous_parser.add_argument("--deployment", required=True)
    autonomous_parser.add_argument("--metric", required=True)
    autonomous_parser.add_argument("--threshold", type=float, required=True)
    autonomous_parser.add_argument("--evidence-value", type=float)
    autonomous_parser.add_argument("--desired-replicas", type=int, default=1)
    autonomous_parser.add_argument("--available-replicas", type=int, default=1)
    autonomous_parser.add_argument("--restart-count", type=int, default=0)
    autonomous_parser.add_argument("--latency-ms", type=float)
    autonomous_parser.add_argument("--error-rate", type=float)
    autonomous_parser.add_argument("--max-replan-attempts", type=int, default=1)
    autonomous_parser.add_argument(
        "--force-recovery-failure",
        action="store_true",
        help="Mock/test option: make the fake recovery monitor fail all actions.",
    )
    autonomous_parser.add_argument(
        "--allowed-namespace", action="append", required=True
    )
    autonomous_parser.add_argument(
        "--allowed-deployment", action="append", required=True
    )
    autonomous_parser.add_argument("--min-replicas", type=int, default=1)
    autonomous_parser.add_argument("--max-replicas", type=int, default=5)
    _add_result_logging_argument(autonomous_parser)

    mutual_parser = subparsers.add_parser(
        "mutual-supervision-run",
        help=(
            "Run the safety-bounded 4-Agent mutual-review protocol with "
            "revision, veto, consensus, recovery monitoring, and research logs."
        ),
    )
    mutual_parser.add_argument(
        "--mode", choices=[mode.value for mode in ExecutionMode], default="mock"
    )
    _add_guard_backend_argument(mutual_parser)
    mutual_parser.add_argument(
        "--evidence-source",
        choices=["fake", "kubernetes"],
        default="fake",
    )
    mutual_parser.add_argument("--namespace", required=True)
    mutual_parser.add_argument("--deployment", required=True)
    mutual_parser.add_argument("--metric", required=True)
    mutual_parser.add_argument("--threshold", type=float, required=True)
    mutual_parser.add_argument("--evidence-value", type=float)
    mutual_parser.add_argument("--desired-replicas", type=int, default=1)
    mutual_parser.add_argument("--available-replicas", type=int, default=1)
    mutual_parser.add_argument("--restart-count", type=int, default=0)
    mutual_parser.add_argument("--latency-ms", type=float)
    mutual_parser.add_argument("--error-rate", type=float)
    mutual_parser.add_argument(
        "--force-recovery-failure",
        action="store_true",
        help="Mock/test option: make the fake recovery monitor fail all actions.",
    )
    mutual_parser.add_argument(
        "--allowed-namespace", action="append", required=True
    )
    mutual_parser.add_argument(
        "--allowed-deployment", action="append", required=True
    )
    mutual_parser.add_argument("--min-replicas", type=int, default=1)
    mutual_parser.add_argument("--max-replicas", type=int, default=5)
    mutual_parser.add_argument(
        "--policy",
        default="config/mutual_supervision_policy.json",
        help="Versioned mutual-review policy JSON path.",
    )
    mutual_parser.add_argument(
        "--protocol-profile",
        default="",
        metavar="ID",
        help=(
            "Select a registered protocol profile by ID. Paths are not "
            "accepted."
        ),
    )
    mutual_parser.add_argument(
        "--output-dir",
        default="runs/mutual-supervision",
        help="Root directory for JSONL, CSV, JSON, and Markdown artifacts.",
    )
    mutual_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Run without writing research artifacts.",
    )

    subparsers.add_parser(
        "list-protocol-profiles",
        help="List repository protocol profiles and their Agent runtimes.",
    )

    list_agents_parser = subparsers.add_parser(
        "list-agents",
        help="List registered 4-Agent research roles and bounded actions.",
    )
    list_agents_parser.add_argument("--registry", default=DEFAULT_AGENT_REGISTRY)
    _add_result_logging_argument(list_agents_parser)

    show_agent_parser = subparsers.add_parser(
        "show-agent",
        help="Show one registered agent profile.",
    )
    show_agent_parser.add_argument("--registry", default=DEFAULT_AGENT_REGISTRY)
    show_agent_parser.add_argument("--agent", required=True)
    _add_result_logging_argument(show_agent_parser)

    validate_agent_parser = subparsers.add_parser(
        "validate-agent-action",
        help="Validate that a bounded action belongs to a registered agent.",
    )
    validate_agent_parser.add_argument("--registry", default=DEFAULT_AGENT_REGISTRY)
    validate_agent_parser.add_argument("--agent", required=True)
    validate_agent_parser.add_argument("--action", required=True)
    _add_result_logging_argument(validate_agent_parser)

    register_agent_parser = subparsers.add_parser(
        "register-agent",
        help="Register or update an AI service-control agent profile.",
    )
    register_agent_parser.add_argument("--registry", default=DEFAULT_AGENT_REGISTRY)
    register_agent_parser.add_argument("--name", required=True)
    register_agent_parser.add_argument("--korean-name", required=True)
    register_agent_parser.add_argument("--role", required=True)
    register_agent_parser.add_argument("--responsibility", action="append", required=True)
    register_agent_parser.add_argument("--action", action="append", required=True)
    register_agent_parser.add_argument("--reward-signal", action="append", required=True)
    register_agent_parser.add_argument("--overwrite", action="store_true")
    _add_result_logging_argument(register_agent_parser)

    partition_parser = subparsers.add_parser(
        "plan-model-partition",
        help=(
            "Generate, validate, and evaluate a logical model partition plan "
            "from an approved federated round plan."
        ),
    )
    _add_partition_planning_arguments(partition_parser)

    partition_v2_parser = subparsers.add_parser(
        "plan-model-partition-v2",
        help="Plan and persist a versioned model partition request.",
    )
    _add_partition_planning_arguments(partition_v2_parser)

    dataset_parser = subparsers.add_parser(
        "build-partition-ranking-dataset",
        help="Build a selected-candidate partition ranking dataset.",
    )
    dataset_parser.add_argument("--artifact-root", action="append", required=True)
    dataset_parser.add_argument("--output", required=True)
    dataset_parser.add_argument("--scope", choices=("observed",), default="observed")
    _add_artifact_signing_key_file_argument(dataset_parser)

    train_ranker_parser = subparsers.add_parser(
        "train-partition-ranker",
        help="Train and register a partition reward ranker.",
    )
    train_ranker_parser.add_argument("--dataset", required=True)
    train_ranker_parser.add_argument("--ranker-registry", required=True)
    train_ranker_parser.add_argument("--model-version", required=True)
    train_ranker_parser.add_argument("--seed", type=int, default=17)
    _add_artifact_signing_key_file_argument(train_ranker_parser)

    evaluate_ranker_parser = subparsers.add_parser(
        "evaluate-partition-ranker",
        help="Evaluate a registered partition reward ranker.",
    )
    evaluate_ranker_parser.add_argument("--dataset", required=True)
    evaluate_ranker_parser.add_argument("--ranker-registry", required=True)
    evaluate_ranker_parser.add_argument("--model-version", required=True)
    _add_artifact_signing_key_file_argument(evaluate_ranker_parser)

    replan_parser = subparsers.add_parser(
        "replan-model-partition",
        help="Replan a model partition after a supported execution failure.",
    )
    _add_partition_planning_arguments(replan_parser)
    replan_parser.add_argument("--previous-plan", required=True)
    replan_parser.add_argument("--failure", required=True)
    replan_parser.add_argument("--attempt", type=int, default=1)

    feedback_parser = subparsers.add_parser(
        "feedback-model-partition",
        help="Process persisted runtime feedback with bounded repartitioning.",
    )
    feedback_parser.add_argument("--plan-id", required=True)
    feedback_parser.add_argument("--feedback", required=True)
    feedback_parser.add_argument(
        "--policy",
        default="config/model_partition_policy.json",
        help="Versioned model partition policy JSON path.",
    )
    feedback_parser.add_argument(
        "--artifact-root",
        default="runs/model-partition",
        help="Root directory for persisted partition plans.",
    )
    _add_ranker_selection_arguments(feedback_parser, optional_mode=True)

    return parser


def _add_partition_planning_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, help="FederatedRoundPlan JSON path.")
    parser.add_argument(
        "--policy",
        default="config/model_partition_policy.json",
        help="Versioned model partition policy JSON path.",
    )
    parser.add_argument(
        "--artifact-root",
        default="runs/model-partition",
        help="Root directory for partition research artifacts.",
    )
    parser.add_argument(
        "--observed",
        default="",
        help="Optional observed runtime metrics JSON path.",
    )
    _add_artifact_signing_key_file_argument(parser)
    _add_ranker_selection_arguments(parser)


def _add_ranker_selection_arguments(
    parser: argparse.ArgumentParser, *, optional_mode: bool = False
) -> None:
    parser.add_argument(
        "--selection-mode",
        choices=("deterministic", "shadow", "learned_guarded"),
        default="" if optional_mode else "deterministic",
    )
    parser.add_argument("--ranker-registry", default="")
    parser.add_argument("--ranker-model-version", default="")


def _add_artifact_signing_key_file_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifact-signing-key-file",
        default="",
        help="External HMAC key file for observed partition artifacts.",
    )


def _add_alert_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", choices=[mode.value for mode in ExecutionMode], default="mock")
    _add_guard_backend_argument(parser)
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
    _add_guard_backend_argument(parser)
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


def _add_guard_backend_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--guard-backend",
        choices=[backend.value for backend in ExecutionBackend],
        default=os.environ.get(
            "AIOPS_GUARD_BACKEND",
            ExecutionBackend.PYTHON.value,
        ),
        help=(
            "Final Kubernetes action guard backend. Use python for the original "
            "in-process validator, or go to route final execution through "
            "go/aiops-guard."
        ),
    )


def _add_autogen_transcript_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--show-transcript",
        action="store_true",
        help="Include a readable AutoGen agent transcript in metadata.transcript.",
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    decision_provider: DecisionProvider | None = None,
    model_client: Any | None = None,
) -> int:
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

    if args.command == "execute-recovery-action":
        result = execute_recovery_action(args)
        _emit_result(args, result)
        return 0 if result.valid else 2

    if args.command == "score-recovery-experiments":
        report = score_recovery_experiments(args)
        _emit_json_report(args, report)
        return 0

    if args.command == "summarize-recovery-statistics":
        report = summarize_recovery_statistics_cli(args)
        _emit_json_report(args, report)
        return 0 if report["valid"] else 2

    if args.command == "build-action-policy-dataset":
        report = build_action_policy_dataset_cli(args)
        _emit_json_report(args, report)
        return 0 if report["valid"] else 2

    if args.command == "build-partition-ranking-dataset":
        report = build_partition_ranking_dataset_cli(args)
        _emit_json_report(args, report)
        return 0 if report.get("error") is None else 2

    if args.command == "train-partition-ranker":
        report = train_partition_ranker_cli(args)
        _emit_json_report(args, report)
        return 0 if report.get("error") is None else 2

    if args.command == "evaluate-partition-ranker":
        report = evaluate_partition_ranker_cli(args)
        _emit_json_report(args, report)
        return 0 if report.get("error") is None else 2

    if args.command == "recommend-action":
        report = recommend_action_cli(args)
        _emit_json_report(args, report)
        return 0 if report["valid"] else 2

    if args.command == "run-recovery-experiments":
        try:
            report = run_recovery_experiment_matrix(args)
        except ValueError as exc:
            _emit_json_report(
                args,
                {
                    "command": "run-recovery-experiments",
                    "valid": False,
                    "stdout": "",
                    "stderr": str(exc),
                },
            )
            return 2
        _emit_json_report(args, report)
        return 0 if report["valid_measurements"] == report["total_treatments"] else 2

    if args.command == "autonomous-run":
        report = run_autonomous_cli(args)
        _emit_json_report(args, report)
        return 0 if report["valid"] else 2

    if args.command == "mutual-supervision-run":
        report = run_mutual_supervision_cli(
            args,
            decision_provider=decision_provider,
            model_client=model_client,
        )
        _emit_json_report(args, report)
        if report.get("final_status") == "runtime_unavailable":
            return 1
        return 0 if report["valid"] else 2

    if args.command == "list-protocol-profiles":
        report = list_registered_protocol_profiles()
        _emit_json_report(args, report)
        return 0

    if args.command == "list-agents":
        report = list_registered_agents(args)
        _emit_json_report(args, report)
        return 0

    if args.command == "show-agent":
        report = show_registered_agent(args)
        _emit_json_report(args, report)
        return 0 if report["valid"] else 2

    if args.command == "validate-agent-action":
        report = validate_registered_agent_action(args)
        _emit_json_report(args, report)
        return 0 if report["valid"] else 2

    if args.command == "register-agent":
        report = register_agent_profile(args)
        _emit_json_report(args, report)
        return 0 if report["valid"] else 2

    if args.command in {"plan-model-partition", "replan-model-partition"}:
        report = run_model_partition_cli(args)
        _emit_json_report(args, report)
        return 0 if report.get("status") == "planned" else 2

    if args.command == "plan-model-partition-v2":
        report = run_model_partition_cli(args)
        _emit_json_report(args, report)
        return 0 if report.get("error") is None else 2

    if args.command == "feedback-model-partition":
        report = run_partition_feedback_cli(args)
        _emit_json_report(args, report)
        return 0 if report.get("error") is None else 2

    parser.error(f"unsupported command: {args.command}")
    return 2


def run_model_partition_cli(args: argparse.Namespace) -> dict[str, Any]:
    try:
        payload = _load_json_object(args.input)
        observed = _load_json_object(args.observed) if args.observed else None
        replanning: dict[str, Any] = {}
        if args.command == "replan-model-partition":
            replanning = {
                "previous_plan_payload": _load_json_object(args.previous_plan),
                "failure_payload": _load_json_object(args.failure),
                "replan_attempt": args.attempt,
            }
        return run_partition_planning(
            payload,
            policy_path=args.policy,
            artifact_root=args.artifact_root,
            observed=observed,
            selection_mode=args.selection_mode,
            ranker_registry_root=args.ranker_registry or None,
            ranker_model_version=args.ranker_model_version or None,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
            **replanning,
        )
    except PartitionContractError as exc:
        return {
            "kind": "model_partition_orchestration",
            "status": "blocked",
            "valid": False,
            "error": {"code": exc.code, "message": exc.message},
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            "kind": "model_partition_orchestration",
            "status": "blocked",
            "valid": False,
            "error": {"code": "invalid_input", "message": str(exc)},
        }


def run_partition_feedback_cli(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return run_partition_feedback(
            args.plan_id,
            _load_json_object(args.feedback),
            PartitionPlanRepository(args.artifact_root, policy_path=args.policy),
            args.policy,
            selection_mode=args.selection_mode or None,
            ranker_registry_root=args.ranker_registry or None,
            ranker_model_version=args.ranker_model_version or None,
        )
    except PartitionContractError as exc:
        return {
            "kind": "model_partition_orchestration",
            "status": "blocked",
            "valid": False,
            "error": {"code": exc.code, "message": exc.message},
        }
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            "kind": "model_partition_orchestration",
            "status": "blocked",
            "valid": False,
            "error": {"code": "invalid_input", "message": str(exc)},
        }


def build_partition_ranking_dataset_cli(args: argparse.Namespace) -> dict[str, Any]:
    try:
        output_path = Path(args.output).expanduser().resolve()
        roots = tuple(Path(root).expanduser().resolve() for root in args.artifact_root)
        summary = build_partition_ranking_dataset(
            roots,
            output_path,
            scope=args.scope,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
        )
        return {
            "command": "build-partition-ranking-dataset",
            "artifact_roots": [str(root) for root in roots],
            "dataset_path": str(output_path),
            "manifest_path": str(summary.manifest_path),
            "dataset_hash": summary.dataset_hash,
            "scope": summary.scope,
            "row_count": summary.row_count,
            "rejections": summary.rejections,
        }
    except (OSError, ValueError, PartitionContractError) as exc:
        return _partition_ranker_cli_error("build-partition-ranking-dataset", exc)


def train_partition_ranker_cli(args: argparse.Namespace) -> dict[str, Any]:
    try:
        summary = train_partition_ranker(
            args.dataset,
            registry_root=args.ranker_registry,
            model_version=args.model_version,
            seed=args.seed,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
        )
        return {
            "command": "train-partition-ranker",
            "dataset_path": str(Path(args.dataset).expanduser().resolve()),
            "ranker_registry": str(Path(args.ranker_registry).expanduser().resolve()),
            "dataset_hash": summary.artifact.training_dataset_hash,
            "scope": summary.artifact.training_scope,
            "model_version": summary.model_version,
            "artifact_path": str(summary.artifact_path),
            "artifact_hash": summary.artifact.artifact_hash,
            "metrics": summary.validation_metrics,
            "guarded_eligible": summary.deployment_eligible,
        }
    except (OSError, ValueError, PartitionContractError) as exc:
        return _partition_ranker_cli_error("train-partition-ranker", exc)


def evaluate_partition_ranker_cli(args: argparse.Namespace) -> dict[str, Any]:
    try:
        artifact = PartitionRankerRepository(args.ranker_registry).get(args.model_version)
        dataset = load_partition_ranking_dataset(
            args.dataset,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
        )
        evaluation = evaluate_partition_ranker(
            dataset.path,
            artifact,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
        )
        return {
            "command": "evaluate-partition-ranker",
            "dataset_path": str(dataset.path),
            "dataset_hash": dataset.dataset_hash,
            "ranker_registry": str(Path(args.ranker_registry).expanduser().resolve()),
            "scope": evaluation.scope,
            "model_version": artifact.model_version,
            "artifact_hash": artifact.artifact_hash,
            "metrics": evaluation.metrics,
            "guarded_eligible": evaluation.deployment_eligible,
        }
    except (OSError, ValueError, PartitionContractError) as exc:
        return _partition_ranker_cli_error("evaluate-partition-ranker", exc)


def _partition_ranker_cli_error(command: str, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, PartitionContractError):
        error = {"code": exc.code, "message": exc.message}
    else:
        error = {"code": "invalid_input", "message": str(exc)}
    return {"command": command, "valid": False, "error": error}


def _load_json_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return payload


def list_registered_agents(args: argparse.Namespace) -> dict[str, Any]:
    registry = load_agent_registry(args.registry)
    return {
        "command": "list-agents",
        "registry": args.registry,
        "version": registry.version,
        "agents": [registry.agents[name].to_dict() for name in registry.agent_names()],
    }


def list_registered_protocol_profiles() -> dict[str, Any]:
    profiles = _load_registered_protocol_profiles()
    return {
        "command": "list-protocol-profiles",
        "profiles": [
            {
                "profile_id": profile.profile_id,
                "version": profile.version,
                "consensus_strategy": profile.consensus_strategy.value,
                "active_agents": [
                    binding.name for binding in profile.enabled_agents
                ],
                "runtimes": {
                    binding.name: binding.runtime
                    for binding in profile.enabled_agents
                },
                "config_hash": profile.config_hash,
            }
            for profile in sorted(
                profiles.values(),
                key=lambda item: item.profile_id,
            )
        ],
    }


def show_registered_agent(args: argparse.Namespace) -> dict[str, Any]:
    try:
        profile = load_agent_registry(args.registry).get(args.agent)
    except AgentRegistryError as exc:
        return {
            "command": "show-agent",
            "valid": False,
            "registry": args.registry,
            "agent": args.agent,
            "stderr": str(exc),
        }
    return {
        "command": "show-agent",
        "valid": True,
        "registry": args.registry,
        "agent": profile.to_dict(),
    }


def validate_registered_agent_action(args: argparse.Namespace) -> dict[str, Any]:
    try:
        registry = load_agent_registry(args.registry)
        valid = registry.validate_action(args.agent, args.action)
        stderr = "" if valid else "action is not allowed for the selected agent"
    except AgentRegistryError as exc:
        valid = False
        stderr = str(exc)
    return {
        "command": "validate-agent-action",
        "valid": valid,
        "registry": args.registry,
        "agent": args.agent,
        "action": args.action,
        "stderr": stderr,
    }


def register_agent_profile(args: argparse.Namespace) -> dict[str, Any]:
    registry_path = Path(args.registry)
    try:
        registry = (
            load_agent_registry(registry_path)
            if registry_path.exists()
            else AgentRegistry(version="1", agents={})
        )
        profile = AgentProfile(
            name=args.name,
            korean_name=args.korean_name,
            role=args.role,
            responsibilities=tuple(args.responsibility),
            bounded_actions=tuple(args.action),
            reward_signals=tuple(args.reward_signal),
        )
        registry.upsert(profile, overwrite=args.overwrite)
        save_agent_registry(registry, registry_path)
    except AgentRegistryError as exc:
        return {
            "command": "register-agent",
            "valid": False,
            "registry": args.registry,
            "agent": args.name,
            "stderr": str(exc),
        }
    return {
        "command": "register-agent",
        "valid": True,
        "registry": args.registry,
        "agent": profile.to_dict(),
        "stderr": "",
    }


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


def execute_recovery_action(args: argparse.Namespace) -> CommandResult:
    validator = _validator_from_args(args)
    action = RecoveryAction(
        namespace=args.namespace,
        deployment=args.deployment,
        kind=RecoveryActionKind(args.action),
        replicas=args.replicas,
        reason=args.reason,
    )
    try:
        return KubernetesExecutor(
            validator=validator,
            mode=ExecutionMode(args.mode),
            backend=ExecutionBackend(args.guard_backend),
        ).execute_recovery(action)
    except (CommandValidationError, ValueError) as exc:
        return _error_result(
            args.mode,
            str(exc),
            {"controller": "bounded-recovery-experiment"},
        )


def score_recovery_experiments(args: argparse.Namespace) -> dict[str, Any]:
    outcomes = load_recovery_outcomes(args.input)
    report = analyze_recovery_outcomes(outcomes)
    write_recovery_analysis(report, args.output_dir)
    return report


def summarize_recovery_statistics_cli(args: argparse.Namespace) -> dict[str, Any]:
    report = summarize_recovery_statistics(args.input)
    write_recovery_statistics(report, args.output_dir)
    report["output_dir"] = args.output_dir
    return report


def build_action_policy_dataset_cli(args: argparse.Namespace) -> dict[str, Any]:
    try:
        samples = load_policy_samples(args.input)
        output = write_policy_samples(samples, args.output)
    except (OSError, ValueError) as exc:
        return {
            "command": "build-action-policy-dataset",
            "valid": False,
            "input": args.input,
            "output": args.output,
            "stderr": str(exc),
        }
    return {
        "command": "build-action-policy-dataset",
        "valid": True,
        "input": args.input,
        **output,
    }


def recommend_action_cli(args: argparse.Namespace) -> dict[str, Any]:
    try:
        policy = ContextualBanditPolicy(mode=args.mode)
        if args.mode == "learned":
            if not args.samples:
                raise ValueError("--samples is required for learned mode")
            policy.fit(load_policy_samples(args.samples))
        context = PolicyContext(
            scenario=args.scenario,
            metric=args.metric,
            cause=args.cause,
            severity=args.severity,
        )
        recommendation = policy.recommend(context)
    except (OSError, ValueError) as exc:
        return {
            "command": "recommend-action",
            "valid": False,
            "stderr": str(exc),
        }
    return {
        "command": "recommend-action",
        "valid": True,
        "samples": args.samples,
        **recommendation.to_dict(),
    }


def run_recovery_experiment_matrix(args: argparse.Namespace) -> dict[str, Any]:
    config = load_recovery_experiment_config(args.config)
    return run_recovery_matrix(
        config=config,
        repetitions=args.repetitions,
        mode=args.mode,
        guard_backend=args.guard_backend,
        prometheus_url=args.prometheus_url,
        output_path=args.output,
    )


def run_autonomous_cli(args: argparse.Namespace) -> dict[str, Any]:
    validator = _validator_from_args(args)
    provider = _evidence_provider_from_args(args)
    monitor = FakeRecoveryMonitor(default_success=not args.force_recovery_failure)
    coordinator = AutonomousAIOpsCoordinator(
        validator=validator,
        evidence_provider=provider,
        recovery_monitor=monitor,
        mode=ExecutionMode(args.mode),
        backend=ExecutionBackend(args.guard_backend),
        max_replan_attempts=args.max_replan_attempts,
    )
    return coordinator.run(
        namespace=args.namespace,
        deployment=args.deployment,
        metric=args.metric,
        threshold=args.threshold,
    )


def run_mutual_supervision_cli(
    args: argparse.Namespace,
    *,
    decision_provider: DecisionProvider | None = None,
    model_client: Any | None = None,
) -> dict[str, Any]:
    try:
        protocol = _select_protocol_profile(
            getattr(args, "protocol_profile", "")
        )
    except ValueError as exc:
        return _mutual_supervision_boundary_failure(
            args,
            final_status="configuration_rejected",
            stderr=str(exc),
        )

    policy = (
        None
        if protocol is not None
        else load_mutual_supervision_policy(args.policy)
    )
    effective_protocol = resolve_mutual_supervision_protocol(protocol, policy)
    uses_autogen = (
        any(
            binding.runtime == AUTOGEN_RUNTIME
            for binding in effective_protocol.enabled_agents
        )
    )
    if uses_autogen and decision_provider is None and model_client is None:
        return _mutual_supervision_boundary_failure(
            args,
            final_status="runtime_unavailable",
            stderr=(
                "the selected protocol requires an explicitly supplied "
                "AutoGen model client or decision provider"
            ),
            protocol=effective_protocol,
        )

    if args.mode == ExecutionMode.REAL.value and args.evidence_source != "kubernetes":
        return _mutual_supervision_boundary_failure(
            args,
            final_status="configuration_rejected",
            stderr=(
                "real mutual supervision requires kubernetes evidence via "
                "--evidence-source kubernetes; "
                "fake evidence cannot verify a real recovery"
            ),
            protocol=effective_protocol,
        )
    adapter_registry = None
    if uses_autogen:
        try:
            adapter_registry = build_autogen_agent_adapter_registry(
                model_client=model_client,
                decision_provider=decision_provider,
            )
        except (RuntimeError, ValueError) as exc:
            return _mutual_supervision_boundary_failure(
                args,
                final_status="runtime_unavailable",
                stderr=str(exc),
                protocol=effective_protocol,
            )
    evidence_provider = _evidence_provider_from_args(args)
    event_store = None
    if not args.no_save:
        experiment_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        event_store = JsonlResearchEventStore(
            root_dir=args.output_dir,
            experiment_id=experiment_id,
            experiment_config={
                "policy_version": (
                    protocol.version
                    if protocol is not None
                    else policy.version
                ),
                "protocol_profile": (
                    protocol.profile_id
                    if protocol is not None
                    else "legacy-default"
                ),
                "mode": args.mode,
                "guard_backend": args.guard_backend,
                "evidence_source": args.evidence_source,
                "namespace": args.namespace,
                "deployment": args.deployment,
                "metric": args.metric,
                "threshold": args.threshold,
            },
        )
    try:
        coordinator = MutualSupervisionCoordinator(
            validator=_validator_from_args(args),
            evidence_provider=evidence_provider,
            recovery_monitor=(
                KubernetesSnapshotRecoveryMonitor(
                    evidence_provider=evidence_provider,
                )
                if args.mode == ExecutionMode.REAL.value
                else FakeRecoveryMonitor(
                    default_success=not args.force_recovery_failure
                )
            ),
            policy=policy,
            protocol=effective_protocol,
            adapter_registry=adapter_registry,
            mode=ExecutionMode(args.mode),
            backend=ExecutionBackend(args.guard_backend),
            event_store=event_store,
        )
    except (AgentRegistryError, ValueError) as exc:
        return _mutual_supervision_boundary_failure(
            args,
            final_status="configuration_rejected",
            stderr=str(exc),
            protocol=protocol,
        )
    return coordinator.run(
        namespace=args.namespace,
        deployment=args.deployment,
        metric=args.metric,
        threshold=args.threshold,
    )


def _load_registered_protocol_profiles() -> dict[str, ResearchProtocolProfile]:
    return load_protocol_profiles(PROTOCOL_PROFILE_DIRECTORY)


def _select_protocol_profile(
    profile_id: str,
) -> ResearchProtocolProfile | None:
    if not profile_id:
        return None
    profiles = _load_registered_protocol_profiles()
    try:
        return profiles[profile_id]
    except KeyError as exc:
        raise ValueError(
            f"unknown protocol profile id: {profile_id}"
        ) from exc


def _mutual_supervision_boundary_failure(
    args: argparse.Namespace,
    *,
    final_status: str,
    stderr: str,
    protocol: ResearchProtocolProfile | None = None,
) -> dict[str, Any]:
    active_agents = (
        [binding.name for binding in protocol.enabled_agents]
        if protocol is not None
        else []
    )
    agent_runtimes = (
        {
            binding.name: binding.runtime
            for binding in protocol.enabled_agents
        }
        if protocol is not None
        else {}
    )
    profile_identity = (
        {
            "profile_id": protocol.profile_id,
            "version": protocol.version,
            "config_hash": protocol.config_hash,
        }
        if protocol is not None
        else {}
    )
    profile_snapshot = (
        protocol.to_canonical_dict()
        if protocol is not None
        else {}
    )
    return {
        "command": "mutual-supervision-run",
        "valid": False,
        "mode": args.mode,
        "final_status": final_status,
        "stderr": stderr,
        "protocol_profile": profile_identity,
        "protocol_profile_snapshot": profile_snapshot,
        "active_agents": active_agents,
        "agent_runtimes": agent_runtimes,
        "safety_validation": {
            "valid": False,
            "command": "",
            "stderr": "no action validated",
        },
        "execution_result": {
            "command": "",
            "mode": args.mode,
            "valid": False,
            "stdout": "",
            "stderr": stderr,
            "metadata": {},
        },
        "executed_actions": [],
        "human_review_required": True,
        "metadata": {
            "coordinator": "AI-MCMP",
            "controller": mutual_supervision_controller_name(
                agent_runtimes.values()
            ),
            "runtime_boundary": final_status,
            "agent_runtimes": agent_runtimes,
        },
    }


def _evidence_provider_from_args(
    args: argparse.Namespace,
) -> FakeEvidenceProvider | KubernetesEvidenceProvider:
    if args.evidence_source == "kubernetes":
        return KubernetesEvidenceProvider()

    metric = str(args.metric).strip().lower().replace("-", "_")
    value = args.evidence_value
    if value is None:
        value = args.threshold + 1.0
    snapshot = EvidenceSnapshot(
        namespace=args.namespace,
        deployment=args.deployment,
        metric_values={metric: value},
        desired_replicas=args.desired_replicas,
        available_replicas=args.available_replicas,
        restart_count=args.restart_count,
        events=("fake evidence for autonomous-run",),
        latency_ms=args.latency_ms,
        error_rate=args.error_rate,
        source="fake",
    )
    return FakeEvidenceProvider(snapshot)


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
        backend=ExecutionBackend(args.guard_backend),
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
            backend=ExecutionBackend(args.guard_backend),
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
            backend=ExecutionBackend(args.guard_backend),
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

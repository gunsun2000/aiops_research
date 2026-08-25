from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from orchestrator_agent.federated_coordination_adapter import (
    load_mapping_context_providers,
)
from orchestrator_agent.partition_learning import (
    build_partition_ranking_dataset,
    evaluate_partition_ranker,
    load_partition_ranking_dataset,
    train_partition_ranker,
)
from orchestrator_agent.partition_models import PartitionContractError
from orchestrator_agent.partition_ranker_repository import PartitionRankerRepository
from orchestrator_agent.partition_repository import PartitionPlanRepository
from orchestrator_agent.partition_service import (
    run_federated_coordination_planning,
    run_partition_feedback,
    run_partition_planning,
)


DEFAULT_POLICY = "config/model_partition_policy.json"
DEFAULT_ARTIFACT_ROOT = "runs/model-partition"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator-agent",
        description="Model Partition Orchestrator Agent research CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("plan-model-partition", "Plan from a legacy FederatedRoundPlan."),
        ("plan-model-partition-v2", "Plan from a versioned partition request."),
    ):
        command = subparsers.add_parser(name, help=help_text)
        _add_planning_arguments(command)

    coordination = subparsers.add_parser(
        "plan-federated-coordination",
        help="Adapt a Federated Coordination v0.4 plan and generate a partition plan.",
    )
    _add_planning_arguments(coordination)
    coordination.add_argument("--context", required=True)

    replan = subparsers.add_parser(
        "replan-model-partition",
        help="Replan after a supported execution failure.",
    )
    _add_planning_arguments(replan)
    replan.add_argument("--previous-plan", required=True)
    replan.add_argument("--failure", required=True)
    replan.add_argument("--attempt", type=int, default=1)

    feedback = subparsers.add_parser(
        "feedback-model-partition",
        help="Process runtime feedback with bounded repartitioning.",
    )
    feedback.add_argument("--plan-id", required=True)
    feedback.add_argument("--feedback", required=True)
    feedback.add_argument("--policy", default=DEFAULT_POLICY)
    feedback.add_argument("--artifact-root", default=DEFAULT_ARTIFACT_ROOT)
    _add_ranker_arguments(feedback, optional_mode=True)

    dataset = subparsers.add_parser(
        "build-partition-ranking-dataset",
        help="Build an observed candidate-ranking dataset.",
    )
    dataset.add_argument("--artifact-root", action="append", required=True)
    dataset.add_argument("--output", required=True)
    dataset.add_argument("--scope", choices=("observed",), default="observed")
    _add_signing_key_argument(dataset)

    train = subparsers.add_parser("train-partition-ranker")
    train.add_argument("--dataset", required=True)
    train.add_argument("--ranker-registry", required=True)
    train.add_argument("--model-version", required=True)
    train.add_argument("--seed", type=int, default=17)
    _add_signing_key_argument(train)

    evaluate = subparsers.add_parser("evaluate-partition-ranker")
    evaluate.add_argument("--dataset", required=True)
    evaluate.add_argument("--ranker-registry", required=True)
    evaluate.add_argument("--model-version", required=True)
    _add_signing_key_argument(evaluate)
    return parser


def _add_planning_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--artifact-root", default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--observed", default="")
    _add_signing_key_argument(parser)
    _add_ranker_arguments(parser)


def _add_ranker_arguments(
    parser: argparse.ArgumentParser, *, optional_mode: bool = False
) -> None:
    parser.add_argument(
        "--selection-mode",
        choices=("deterministic", "shadow", "learned_guarded"),
        default="" if optional_mode else "deterministic",
    )
    parser.add_argument("--ranker-registry", default="")
    parser.add_argument("--ranker-model-version", default="")


def _add_signing_key_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifact-signing-key-file", default="")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = _run(args)
    except PartitionContractError as exc:
        report = _error(exc.code, exc.message)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        report = _error("invalid_input", str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report.get("error") else 0


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command in {"plan-model-partition", "plan-model-partition-v2"}:
        return _run_plan(args)
    if args.command == "plan-federated-coordination":
        participant_provider, model_provider = load_mapping_context_providers(
            args.context
        )
        return run_federated_coordination_planning(
            _load_json_object(args.input),
            participant_provider=participant_provider,
            model_provider=model_provider,
            policy_path=args.policy,
            artifact_root=args.artifact_root,
            observed=_load_json_object(args.observed) if args.observed else None,
            selection_mode=args.selection_mode,
            ranker_registry_root=args.ranker_registry or None,
            ranker_model_version=args.ranker_model_version or None,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
        )
    if args.command == "replan-model-partition":
        return run_partition_planning(
            _load_json_object(args.input),
            policy_path=args.policy,
            artifact_root=args.artifact_root,
            observed=_load_json_object(args.observed) if args.observed else None,
            previous_plan_payload=_load_json_object(args.previous_plan),
            failure_payload=_load_json_object(args.failure),
            replan_attempt=args.attempt,
            selection_mode=args.selection_mode,
            ranker_registry_root=args.ranker_registry or None,
            ranker_model_version=args.ranker_model_version or None,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
        )
    if args.command == "feedback-model-partition":
        return run_partition_feedback(
            args.plan_id,
            _load_json_object(args.feedback),
            PartitionPlanRepository(args.artifact_root, policy_path=args.policy),
            args.policy,
            selection_mode=args.selection_mode or None,
            ranker_registry_root=args.ranker_registry or None,
            ranker_model_version=args.ranker_model_version or None,
        )
    if args.command == "build-partition-ranking-dataset":
        summary = build_partition_ranking_dataset(
            tuple(Path(root).expanduser().resolve() for root in args.artifact_root),
            Path(args.output).expanduser().resolve(),
            scope=args.scope,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
        )
        return {
            "command": args.command,
            "dataset_path": str(Path(args.output).expanduser().resolve()),
            "manifest_path": str(summary.manifest_path),
            "dataset_hash": summary.dataset_hash,
            "scope": summary.scope,
            "row_count": summary.row_count,
            "rejections": summary.rejections,
        }
    if args.command == "train-partition-ranker":
        summary = train_partition_ranker(
            args.dataset,
            registry_root=args.ranker_registry,
            model_version=args.model_version,
            seed=args.seed,
            artifact_signing_key_file=args.artifact_signing_key_file or None,
        )
        return {
            "command": args.command,
            "model_version": summary.model_version,
            "artifact_path": str(summary.artifact_path),
            "metrics": summary.validation_metrics,
            "guarded_eligible": summary.deployment_eligible,
        }
    if args.command == "evaluate-partition-ranker":
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
            "command": args.command,
            "model_version": artifact.model_version,
            "scope": evaluation.scope,
            "metrics": evaluation.metrics,
            "guarded_eligible": evaluation.deployment_eligible,
        }
    raise ValueError(f"unsupported command: {args.command}")


def _run_plan(args: argparse.Namespace) -> dict[str, Any]:
    return run_partition_planning(
        _load_json_object(args.input),
        policy_path=args.policy,
        artifact_root=args.artifact_root,
        observed=_load_json_object(args.observed) if args.observed else None,
        selection_mode=args.selection_mode,
        ranker_registry_root=args.ranker_registry or None,
        ranker_model_version=args.ranker_model_version or None,
        artifact_signing_key_file=args.artifact_signing_key_file or None,
    )


def _load_json_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return payload


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "kind": "model_partition_orchestration",
        "status": "blocked",
        "valid": False,
        "error": {"code": code, "message": message},
    }


if __name__ == "__main__":
    raise SystemExit(main())

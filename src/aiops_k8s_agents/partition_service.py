from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_artifacts import write_partition_report
from aiops_k8s_agents.partition_evaluator import (
    ObservedPartitionMetrics,
    PartitionPlanEvaluator,
)
from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionExecutionPlan,
    PartitionFailure,
)
from aiops_k8s_agents.partition_repository import SchedulingHandoff
from aiops_k8s_agents.partition_validator import PartitionPlanValidator


def run_partition_planning(
    payload: Mapping[str, Any],
    *,
    policy_path: str | Path,
    artifact_root: str | Path,
    observed: Mapping[str, Any] | None = None,
    previous_plan_payload: Mapping[str, Any] | None = None,
    failure_payload: Mapping[str, Any] | None = None,
    replan_attempt: int = 1,
    plan_id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    round_plan = FederatedRoundPlan.from_dict(payload)
    policy = ModelPartitionPolicy.from_path(policy_path)
    agent = ModelPartitionOrchestrationAgent(
        policy, plan_id_factory=plan_id_factory
    )
    replanning: dict[str, Any] | None = None
    if previous_plan_payload is not None or failure_payload is not None:
        if previous_plan_payload is None or failure_payload is None:
            raise ValueError(
                "previous_plan_payload and failure_payload must be provided together"
            )
        previous_plan = PartitionExecutionPlan.from_dict(previous_plan_payload)
        failure = PartitionFailure.from_dict(failure_payload)
        plan = agent.replan(
            round_plan,
            previous_plan,
            failure,
            attempt=replan_attempt,
        )
        replanning = {
            "attempt": replan_attempt,
            "failure": failure.to_dict(),
            "previous_plan_id": previous_plan.plan_id,
        }
    else:
        plan = agent.plan(round_plan)
    validation = PartitionPlanValidator().validate(round_plan, plan)
    observed_metrics = (
        None if observed is None else ObservedPartitionMetrics.from_dict(observed)
    )
    evaluation = PartitionPlanEvaluator(policy).evaluate(
        round_plan,
        plan,
        validation,
        observed=observed_metrics,
    )
    report = {
        "schema_version": "1.0",
        "kind": "model_partition_orchestration",
        "status": "planned" if plan.valid and validation.valid else "blocked",
        "round_plan": round_plan.to_dict(),
        "plan": plan.to_dict(),
        "validation": validation.to_dict(),
        "evaluation": evaluation.to_dict(),
        "replanning": replanning,
    }
    report["scheduling_handoff"] = SchedulingHandoff.create(
        plan,
        id_factory=lambda: f"scheduling-handoff-{uuid4().hex}",
        clock=lambda: datetime.now(timezone.utc).isoformat(),
    ).to_dict()
    artifact_path = write_partition_report(report, artifact_root)
    return {**report, "artifact_path": str(artifact_path)}

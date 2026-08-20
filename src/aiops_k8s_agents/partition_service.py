from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_artifacts import write_partition_report
from aiops_k8s_agents.partition_evaluator import (
    ObservedPartitionMetrics,
    PartitionPlanEvaluator,
)
from aiops_k8s_agents.partition_coordination import PartitionPlanningRequest
from aiops_k8s_agents.partition_feedback import (
    PartitionFeedbackAnalyzer,
    PartitionRuntimeFeedback,
    RepartitionDirective,
)
from aiops_k8s_agents.partition_models import (
    FederatedRoundPlan,
    PartitionContractError,
    PartitionExecutionPlan,
    PartitionFailure,
)
from aiops_k8s_agents.partition_repository import (
    PartitionPlanRepository,
    SchedulingHandoff,
)
from aiops_k8s_agents.partition_strategies import PartitionStrategyRegistry
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
    v2_request: bool | None = None,
) -> dict[str, Any]:
    policy = ModelPartitionPolicy.from_path(policy_path)
    strategy_registry = PartitionStrategyRegistry.default(Path(policy_path))
    agent = ModelPartitionOrchestrationAgent(
        policy,
        plan_id_factory=plan_id_factory,
        strategy_registry=strategy_registry,
    )
    is_v2_request = "coordination_plan" in payload if v2_request is None else v2_request
    planning_request = (
        PartitionPlanningRequest.from_dict(payload) if is_v2_request else None
    )
    round_plan = (
        agent._round_plan_from_normalized(
            agent._common_processor.process(planning_request)
        )
        if planning_request is not None
        else FederatedRoundPlan.from_dict(payload)
    )
    replanning: dict[str, Any] | None = None
    if previous_plan_payload is not None or failure_payload is not None:
        if planning_request is not None:
            raise PartitionContractError(
                "legacy_replan_context_not_supported",
                "V2 partition requests must use persisted feedback replanning",
            )
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
        plan = (
            agent.plan_request(planning_request)
            if planning_request is not None
            else agent.plan(round_plan)
        )
    validation = PartitionPlanValidator(strategy_registry=strategy_registry).validate(
        planning_request or round_plan, plan
    )
    observed_metrics = (
        None if observed is None else ObservedPartitionMetrics.from_dict(observed)
    )
    evaluation = PartitionPlanEvaluator(
        policy, strategy_registry=strategy_registry
    ).evaluate(
        planning_request or round_plan,
        plan,
        validation,
        observed=observed_metrics,
    )
    report = {
        "schema_version": "1.0",
        "kind": "model_partition_orchestration",
        "status": "planned" if plan.valid and validation.valid else "blocked",
        **(
            {"planning_request": dict(payload)}
            if planning_request is not None
            else {}
        ),
        "round_plan": round_plan.to_dict(),
        "plan": plan.to_dict(),
        "validation": validation.to_dict(),
        "evaluation": evaluation.to_dict(),
        "replanning": replanning,
    }
    if report["status"] == "blocked":
        report["scheduling_handoff"] = SchedulingHandoff.create(
            plan,
            id_factory=lambda: f"scheduling-handoff-{plan.plan_id}",
            clock=lambda: datetime.now(timezone.utc).isoformat(),
        ).to_dict()
    artifact_path = write_partition_report(
        report, artifact_root, policy_path=policy_path
    )
    return {**report, "artifact_path": str(artifact_path)}


class PartitionFeedbackService:
    """Replan from recorded feedback without scheduling or runtime execution."""

    def __init__(
        self,
        repository: PartitionPlanRepository,
        policy_path: str | Path,
        *,
        plan_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = ModelPartitionPolicy.from_path(policy_path)
        self._strategy_registry = PartitionStrategyRegistry.default(Path(policy_path))
        self._plan_id_factory = plan_id_factory
        self._analyzer = PartitionFeedbackAnalyzer()

    def process_feedback(
        self,
        plan_id: str,
        feedback: Mapping[str, Any] | PartitionRuntimeFeedback,
    ) -> dict[str, Any]:
        runtime_feedback = (
            feedback.validate()
            if isinstance(feedback, PartitionRuntimeFeedback)
            else PartitionRuntimeFeedback.from_dict(feedback)
        )
        if runtime_feedback.plan_id != plan_id:
            raise PartitionContractError(
                "feedback_plan_mismatch",
                "feedback plan_id must match the requested persisted plan",
            )
        previous_report = self._repository.get(plan_id)
        if not self._repository.is_current_leaf(plan_id):
            raise PartitionContractError(
                "non_current_feedback_plan",
                "feedback must reference the current leaf plan in its lineage",
            )
        previous_plan = PartitionExecutionPlan.from_dict(previous_report["plan"])
        directive = self._analyzer.analyze(runtime_feedback, previous_plan)
        effective_directive = self._prior_exclusions(previous_report).merge(directive)
        round_plan = FederatedRoundPlan.from_dict(previous_report["round_plan"])
        agent = ModelPartitionOrchestrationAgent(
            self._policy,
            plan_id_factory=self._plan_id_factory,
            strategy_registry=self._strategy_registry,
        )
        request_payload = previous_report.get("planning_request")
        request = (
            PartitionPlanningRequest.from_dict(request_payload)
            if isinstance(request_payload, Mapping)
            else None
        )
        plan = (
            agent.replan_request(
                request,
                previous_plan,
                effective_directive,
                attempt=previous_plan.plan_version,
            )
            if request is not None
            else agent.replan_with_directive(
                round_plan,
                previous_plan,
                effective_directive,
                attempt=previous_plan.plan_version,
            )
        )
        validation = PartitionPlanValidator(
            strategy_registry=self._strategy_registry
        ).validate(request or round_plan, plan)
        evaluation = PartitionPlanEvaluator(
            self._policy, strategy_registry=self._strategy_registry
        ).evaluate(
            request or round_plan, plan, validation
        )
        report = {
            "schema_version": "1.0",
            "kind": "model_partition_orchestration",
            "status": "planned" if plan.valid and validation.valid else "blocked",
            **(
                {"planning_request": dict(request_payload)}
                if isinstance(request_payload, Mapping)
                else {}
            ),
            "round_plan": round_plan.to_dict(),
            "plan": plan.to_dict(),
            "validation": validation.to_dict(),
            "evaluation": evaluation.to_dict(),
            "replanning": {
                "attempt": previous_plan.plan_version,
                "reason": runtime_feedback.signal,
                "previous_plan_id": previous_plan.plan_id,
                "feedback": runtime_feedback.to_dict(),
                "directive": directive.to_dict(),
                "bounded_exclusions": effective_directive.to_dict(),
            },
        }
        if report["status"] == "planned":
            artifact_path = self._repository.save(
                report,
                sidecars={
                    "runtime_feedback.json": runtime_feedback.to_dict(),
                    "repartition_directive.json": effective_directive.to_dict(),
                },
            )
            return {**report, "artifact_path": str(artifact_path)}

        report["scheduling_handoff"] = SchedulingHandoff.create(
            plan,
            id_factory=lambda: f"scheduling-handoff-{plan.plan_id}",
            clock=lambda: runtime_feedback.received_at,
        ).to_dict()
        return report

    @staticmethod
    def _prior_exclusions(report: Mapping[str, Any]) -> RepartitionDirective:
        replanning = report.get("replanning")
        if not isinstance(replanning, Mapping):
            return RepartitionDirective("none")
        exclusions = replanning.get("bounded_exclusions")
        if not isinstance(exclusions, Mapping):
            return RepartitionDirective("none")
        return RepartitionDirective.from_dict(exclusions)


def run_partition_feedback(
    plan_id: str,
    feedback: Mapping[str, Any] | PartitionRuntimeFeedback,
    repository: PartitionPlanRepository,
    policy_path: str | Path,
    *,
    plan_id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    return PartitionFeedbackService(
        repository, policy_path, plan_id_factory=plan_id_factory
    ).process_feedback(plan_id, feedback)

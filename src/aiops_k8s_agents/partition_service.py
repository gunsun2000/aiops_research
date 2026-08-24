from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from aiops_k8s_agents.federated_coordination_adapter import (
    FederatedCoordinationPlanV04,
    FederatedCoordinationV04Adapter,
    ModelContextProvider,
    ParticipantContextProvider,
    partition_planning_request_to_dict,
)
from aiops_k8s_agents.model_partition_agent import (
    ModelPartitionOrchestrationAgent,
    ModelPartitionPolicy,
)
from aiops_k8s_agents.partition_artifacts import (
    build_runtime_outcome_sidecar,
    write_partition_report,
)
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
from aiops_k8s_agents.partition_ranker_repository import PartitionRankerRepository
from aiops_k8s_agents.partition_ranking import (
    DeterministicPolicyRanker,
    GuardedCandidateSelector,
    LearnedRewardRanker,
)
from aiops_k8s_agents.partition_ranking_models import SelectionMode
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
    selection_mode: str = "deterministic",
    ranker_registry_root: str | Path | None = None,
    ranker_model_version: str | None = None,
    artifact_signing_key: str | bytes | None = None,
    artifact_signing_key_file: str | Path | None = None,
    report_extensions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    policy = ModelPartitionPolicy.from_path(policy_path)
    strategy_registry = PartitionStrategyRegistry.default(Path(policy_path))
    selector = build_candidate_selector(
        policy=policy,
        selection_mode=SelectionMode(selection_mode),
        ranker_repository=(
            None
            if ranker_registry_root is None
            else PartitionRankerRepository(ranker_registry_root)
        ),
        model_version=ranker_model_version,
    )
    agent = ModelPartitionOrchestrationAgent(
        policy,
        plan_id_factory=plan_id_factory,
        strategy_registry=strategy_registry,
        selector=selector,
        selection_mode=SelectionMode(selection_mode),
        ranker_model_version=ranker_model_version,
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
    if report_extensions:
        protected = set(report).intersection(report_extensions)
        if protected:
            raise ValueError(
                f"report extensions cannot replace core keys: {sorted(protected)}"
            )
        report.update(dict(report_extensions))
    if report["status"] == "blocked":
        report["scheduling_handoff"] = SchedulingHandoff.create(
            plan,
            id_factory=lambda: f"scheduling-handoff-{plan.plan_id}",
            clock=lambda: datetime.now(timezone.utc).isoformat(),
        ).to_dict()
    runtime_outcome = build_runtime_outcome_sidecar(report)
    artifact_path = write_partition_report(
        report,
        artifact_root,
        policy_path=policy_path,
        sidecars=(
            {} if runtime_outcome is None else {"runtime_outcome.json": runtime_outcome}
        ),
        artifact_signing_key=artifact_signing_key,
        artifact_signing_key_file=artifact_signing_key_file,
    )
    return {**report, "artifact_path": str(artifact_path)}


def run_federated_coordination_planning(
    payload: Mapping[str, Any],
    *,
    participant_provider: ParticipantContextProvider,
    model_provider: ModelContextProvider,
    policy_path: str | Path,
    artifact_root: str | Path,
    observed: Mapping[str, Any] | None = None,
    plan_id_factory: Callable[[], str] | None = None,
    selection_mode: str = "deterministic",
    ranker_registry_root: str | Path | None = None,
    ranker_model_version: str | None = None,
    artifact_signing_key: str | bytes | None = None,
    artifact_signing_key_file: str | Path | None = None,
) -> dict[str, Any]:
    parsed = FederatedCoordinationPlanV04.from_dict(payload)
    try:
        participant_context = participant_provider.resolve(parsed.participant_ids)
        model_context = model_provider.resolve(parsed.model_id, parsed.model_version)
        request = FederatedCoordinationV04Adapter().adapt(
            parsed, participant_context, model_context
        )
    except PartitionContractError as exc:
        return {
            "schema_version": "1.0",
            "kind": "model_partition_orchestration",
            "status": "blocked",
            "upstream_coordination": parsed.to_dict(),
            "context_enrichment": {
                "status": "blocked",
                "participant_ids": list(parsed.participant_ids),
            },
            "error": {"code": exc.code, "message": exc.message},
        }
    enrichment = {
        "status": "complete",
        "participant_source": participant_context.source,
        "model_source": model_context.source,
        "snapshot_id": participant_context.snapshot_id,
        "snapshot_version": participant_context.snapshot_version,
        "participant_ids": list(parsed.participant_ids),
        "device_count": len(participant_context.devices),
        "network_link_count": len(participant_context.network_links),
        "model_id": parsed.model_id,
        "model_version": parsed.model_version,
        "profile_id": model_context.profile.profile_id,
    }
    return run_partition_planning(
        partition_planning_request_to_dict(request),
        policy_path=policy_path,
        artifact_root=artifact_root,
        observed=observed,
        plan_id_factory=plan_id_factory,
        v2_request=True,
        selection_mode=selection_mode,
        ranker_registry_root=ranker_registry_root,
        ranker_model_version=ranker_model_version,
        artifact_signing_key=artifact_signing_key,
        artifact_signing_key_file=artifact_signing_key_file,
        report_extensions={
            "upstream_coordination": parsed.to_dict(),
            "context_enrichment": enrichment,
        },
    )


def build_candidate_selector(
    *,
    policy: ModelPartitionPolicy,
    selection_mode: SelectionMode,
    ranker_repository: PartitionRankerRepository | None,
    model_version: str | None,
) -> GuardedCandidateSelector:
    """Load a ranker only from the registered repository boundary."""
    mode = SelectionMode(selection_mode)
    if mode is not SelectionMode.DETERMINISTIC and not model_version:
        raise PartitionContractError(
            "ranker_model_version_required",
            "shadow and learned_guarded selection require a registered model version",
        )
    if model_version and ranker_repository is None:
        raise PartitionContractError(
            "ranker_registry_required",
            "an explicitly requested ranker model must be resolved from a registry",
        )
    learned = None
    if ranker_repository is not None and model_version:
        learned = LearnedRewardRanker(ranker_repository.get(model_version))
    return GuardedCandidateSelector(
        deterministic=DeterministicPolicyRanker(),
        learned=learned,
        guard_policy=policy.learned_ranker_guard,
    )


class PartitionFeedbackService:
    """Replan from recorded feedback without scheduling or runtime execution."""

    def __init__(
        self,
        repository: PartitionPlanRepository,
        policy_path: str | Path,
        *,
        plan_id_factory: Callable[[], str] | None = None,
        selection_mode: str | None = None,
        ranker_registry_root: str | Path | None = None,
        ranker_model_version: str | None = None,
    ) -> None:
        self._repository = repository
        self._policy = ModelPartitionPolicy.from_path(policy_path)
        self._strategy_registry = PartitionStrategyRegistry.default(Path(policy_path))
        self._plan_id_factory = plan_id_factory
        self._selection_mode = selection_mode
        self._ranker_registry_root = ranker_registry_root
        self._ranker_model_version = ranker_model_version
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
        previous_selection = previous_plan.selection
        inherited_selection_mode = (
            self._selection_mode
            or ("deterministic" if previous_selection is None else previous_selection.mode)
        )
        inherited_model_version = (
            self._ranker_model_version
            if self._ranker_model_version is not None
            else (None if previous_selection is None else previous_selection.model_version)
        )
        selector = build_candidate_selector(
            policy=self._policy,
            selection_mode=SelectionMode(inherited_selection_mode),
            ranker_repository=(
                None
                if self._ranker_registry_root is None
                else PartitionRankerRepository(self._ranker_registry_root)
            ),
            model_version=inherited_model_version,
        )
        agent = ModelPartitionOrchestrationAgent(
            self._policy,
            plan_id_factory=self._plan_id_factory,
            strategy_registry=self._strategy_registry,
            selector=selector,
            selection_mode=SelectionMode(inherited_selection_mode),
            ranker_model_version=inherited_model_version,
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
                    "candidate_ranking.json": plan.selection.to_dict(),
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
    selection_mode: str | None = None,
    ranker_registry_root: str | Path | None = None,
    ranker_model_version: str | None = None,
) -> dict[str, Any]:
    return PartitionFeedbackService(
        repository,
        policy_path,
        plan_id_factory=plan_id_factory,
        selection_mode=selection_mode,
        ranker_registry_root=ranker_registry_root,
        ranker_model_version=ranker_model_version,
    ).process_feedback(plan_id, feedback)

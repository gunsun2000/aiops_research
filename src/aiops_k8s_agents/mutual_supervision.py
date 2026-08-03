from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import asdict, dataclass, field, replace
import math
from pathlib import Path
from typing import Any, Iterable

from aiops_k8s_agents.agent_adapters import (
    AgentAdapter,
    AgentAdapterRegistry,
    DeterministicApplicationAdapter,
    DeterministicCostAdapter,
    DeterministicHAAdapter,
    DeterministicInfrastructureAdapter,
    ReviewContext,
    build_default_agent_adapter_registry,
)
from aiops_k8s_agents.application_agent import AIApplicationManagementAgent
from aiops_k8s_agents.consensus import ConsensusResolver
from aiops_k8s_agents.cost_agent import CostOptimizationAgent
from aiops_k8s_agents.evidence import EvidenceProvider, EvidenceSnapshot
from aiops_k8s_agents.executor import (
    ExecutionBackend,
    ExecutionMode,
    KubernetesExecutor,
)
from aiops_k8s_agents.ha_agent import AIServiceHASupportAgent
from aiops_k8s_agents.infra_agent import AISemiconductorInfraOpsAgent
from aiops_k8s_agents.models import (
    CommandResult,
    Diagnosis,
    RecoveryAction,
    RecoveryActionCandidate,
    RecoveryActionKind,
)
from aiops_k8s_agents.mutual_supervision_models import (
    NegotiationRound,
    PeerReview,
    PostExecutionReview,
    ReviewVerdict,
    SupervisionDecision,
    new_trace_id,
    to_serializable,
)
from aiops_k8s_agents.mutual_supervision_policy import MutualSupervisionPolicy
from aiops_k8s_agents.operation_lock import (
    OperationLockError,
    TargetOperationLock,
)
from aiops_k8s_agents.recovery_monitor import RecoveryAssessment, RecoveryMonitor
from aiops_k8s_agents.research_event_store import ResearchEventSink
from aiops_k8s_agents.research_protocol import (
    ResearchProtocolProfile,
    load_research_protocol,
)
from aiops_k8s_agents.validator import (
    CommandValidationError,
    CommandValidator,
    render_recovery_command,
)


class AdapterOutputError(ValueError):
    """Raised when a runtime adapter returns an unsafe contract value."""


class ReviewCollectionFailure(AdapterOutputError):
    """Carry valid peer reviews collected before a reviewer failed."""

    def __init__(self, message: str, reviews: list[PeerReview]) -> None:
        super().__init__(message)
        self.reviews = tuple(reviews)


class NegotiationFailure(AdapterOutputError):
    """Carry the valid negotiation trace collected before safe-stop."""

    def __init__(
        self,
        message: str,
        *,
        decisions: list[SupervisionDecision],
        reviews: list[PeerReview],
        rounds: list[NegotiationRound],
    ) -> None:
        super().__init__(message)
        self.decisions = tuple(decisions)
        self.reviews = tuple(reviews)
        self.rounds = tuple(rounds)


class PostReviewFailure(AdapterOutputError):
    """Carry valid post-execution reviews collected before failure."""

    def __init__(
        self,
        message: str,
        reviews: list[PostExecutionReview],
    ) -> None:
        super().__init__(message)
        self.reviews = tuple(reviews)


def resolve_mutual_supervision_protocol(
    protocol: ResearchProtocolProfile | None,
    policy: MutualSupervisionPolicy | None,
) -> ResearchProtocolProfile:
    if protocol is not None:
        return protocol
    default_protocol = load_research_protocol(
        Path(__file__).resolve().parents[2]
        / "config"
        / "protocol_profiles"
        / "four-agent-role-veto-v1.json"
    )
    if policy is None:
        return default_protocol
    return _profile_with_legacy_policy(default_protocol, policy)


def mutual_supervision_controller_name(runtimes: Iterable[str]) -> str:
    active_runtimes = set(runtimes)
    if not active_runtimes or active_runtimes == {"deterministic"}:
        return "mutual_supervision_deterministic"
    if active_runtimes == {"autogen-round-robin"}:
        return "mutual_supervision_autogen"
    return "mutual_supervision_hybrid"


@dataclass
class MutualSupervisionCoordinator:
    validator: CommandValidator
    evidence_provider: EvidenceProvider
    recovery_monitor: RecoveryMonitor
    policy: MutualSupervisionPolicy | None = None
    mode: ExecutionMode = ExecutionMode.MOCK
    backend: ExecutionBackend = ExecutionBackend.PYTHON
    ha_agent: AIServiceHASupportAgent | None = None
    app_agent: AIApplicationManagementAgent | None = None
    infra_agent: AISemiconductorInfraOpsAgent | None = None
    cost_agent: CostOptimizationAgent | None = None
    event_store: ResearchEventSink | None = None
    operation_lock_dir: str | Path | None = None
    operation_lock_owned_externally: bool = False
    runtime_control: Any | None = None
    protocol: ResearchProtocolProfile | None = None
    adapter_registry: AgentAdapterRegistry | None = None
    consensus_resolver: ConsensusResolver = field(default_factory=ConsensusResolver)
    adapters: dict[str, AgentAdapter] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExecutionMode(self.mode)
        if isinstance(self.backend, str):
            self.backend = ExecutionBackend(self.backend)
        self.protocol = resolve_mutual_supervision_protocol(
            self.protocol,
            self.policy,
        )
        if self.adapter_registry is None:
            self.adapter_registry = build_default_agent_adapter_registry()
        self.protocol.validate_integrity()
        created_adapters = self.adapter_registry.create_profile(self.protocol)
        self.adapters = {}
        for binding, adapter in zip(
            self.protocol.enabled_agents,
            created_adapters,
            strict=True,
        ):
            compatible_adapter = self._with_compatibility_agent(adapter)
            self.adapter_registry.validate_adapter(
                binding,
                compatible_adapter,
            )
            self.adapters[binding.name] = compatible_adapter

    def _with_compatibility_agent(self, adapter: AgentAdapter) -> AgentAdapter:
        if isinstance(adapter, DeterministicHAAdapter) and self.ha_agent is not None:
            return replace(adapter, agent=self.ha_agent)
        if (
            isinstance(adapter, DeterministicApplicationAdapter)
            and self.app_agent is not None
        ):
            return replace(adapter, agent=self.app_agent)
        if (
            isinstance(adapter, DeterministicInfrastructureAdapter)
            and self.infra_agent is not None
        ):
            return replace(adapter, agent=self.infra_agent)
        if (
            isinstance(adapter, DeterministicCostAdapter)
            and self.cost_agent is not None
        ):
            return replace(adapter, agent=self.cost_agent)
        return adapter

    def run(
        self,
        namespace: str,
        deployment: str,
        metric: str,
        threshold: float,
    ) -> dict[str, Any]:
        self._check_runtime_control()
        run_id = new_trace_id("run")
        self._begin_adapter_run(run_id)
        self._record(
            "protocol_profiles",
            {
                "run_id": run_id,
                **self._protocol_identity(),
                "consensus_strategy": self.protocol.consensus_strategy.value,
            },
            run_id,
        )
        capability_errors = self._required_capability_errors()
        if capability_errors:
            return self._finalize_report(
                self._configuration_failure_report(
                    run_id=run_id,
                    errors=capability_errors,
                )
            )

        self._check_runtime_control()
        evidence = self.evidence_provider.collect(namespace, deployment)
        self._check_runtime_control()
        self._record("evidence", evidence.to_summary(), run_id)
        diagnosis_adapter = self._single_adapter_for("diagnose")
        try:
            diagnosis_result = diagnosis_adapter.diagnose(
                evidence,
                metric,
                threshold,
            )
            diagnosis, normalized_decision = _normalize_diagnosis_output(
                diagnosis_adapter,
                diagnosis_result,
                run_id=run_id,
                round_index=0,
                policy_version=self.protocol.version,
                evidence_refs=_evidence_refs(evidence, metric),
                expected_service=deployment,
            )
            self._check_runtime_control()
        except Exception as exc:
            report = self._configuration_failure_report(
                run_id=run_id,
                errors=(
                    f"{diagnosis_adapter.name} diagnose failed: {exc}",
                ),
            )
            report["evidence"] = evidence.to_summary()
            return self._finalize_report(report)
        initial_decisions = [normalized_decision]
        self._record("initial_decisions", initial_decisions[0], run_id)
        self._check_runtime_control()

        if not initial_decisions[0].approved:
            missing_requested_metric = (
                diagnosis.cause == "unknown_metric"
                and bool(diagnosis.evidence.get("missing_evidence"))
            )
            return self._finalize_report(
                self._base_report(
                    run_id=run_id,
                    evidence=evidence,
                    diagnosis=diagnosis,
                    initial_decisions=initial_decisions,
                    peer_reviews=[],
                    rounds=[],
                    final_status=(
                        "safe_stopped"
                        if missing_requested_metric
                        else "no_action_required"
                    ),
                    human_review_required=(
                        self.protocol.human_review_on_failure
                        if missing_requested_metric
                        else False
                    ),
                )
            )

        proposal_adapter = self._single_adapter_for("propose")
        try:
            proposed_actions = _normalize_proposal_output(
                proposal_adapter,
                proposal_adapter.propose(diagnosis, evidence),
            )
            self._check_runtime_control()
        except Exception as exc:
            report = self._base_report(
                run_id=run_id,
                evidence=evidence,
                diagnosis=diagnosis,
                initial_decisions=initial_decisions,
                peer_reviews=[],
                rounds=[],
                final_status="safe_stopped",
                human_review_required=self.protocol.human_review_on_failure,
            )
            report["configuration_errors"] = [
                f"{proposal_adapter.name} propose failed: {exc}"
            ]
            return self._finalize_report(report)

        candidates: list[RecoveryActionCandidate] = []
        replanning_attempts: list[dict[str, Any]] = []
        for index, action in enumerate(proposed_actions):
            action_error = _action_semantic_error(
                action,
                protocol=self.protocol,
                evidence=evidence,
                namespace=namespace,
                deployment=deployment,
            )
            if action_error:
                replanning_attempts.append(
                    {
                        "failed_action": action.kind.value,
                        "reason": action_error,
                        "next_step": "human_review_required",
                    }
                )
                continue
            candidates.append(
                RecoveryActionCandidate(
                    action=action,
                    reason=action.reason,
                    expected_effect=action.reason,
                    risk_level="bounded",
                    estimated_cost=0.0,
                    confidence=diagnosis.confidence,
                    priority=max(1.0 - (index * 0.1), 0.0),
                )
            )
        if candidates:
            for attempt in replanning_attempts:
                attempt["next_step"] = "try_next_candidate"
        executor = KubernetesExecutor(
            validator=self.validator,
            mode=self.mode,
            backend=self.backend,
        )
        all_reviews: list[PeerReview] = []
        all_rounds: list[NegotiationRound] = []
        all_post_reviews: list[PostExecutionReview] = []
        executed_actions: list[RecoveryAction] = []
        last_validation: dict[str, Any] = {
            "valid": False,
            "command": "",
            "stderr": "no action validated",
        }
        last_execution = _empty_result(self.mode.value, "no action executed")
        last_assessment: dict[str, Any] = {}
        last_action: RecoveryAction | None = None

        max_attempts = min(
            len(candidates),
            self.protocol.max_replan_attempts + 1,
        )
        for candidate_index, candidate in enumerate(candidates[:max_attempts]):
            try:
                selected_action, decisions, reviews, rounds = self._negotiate(
                    run_id=run_id,
                    diagnosis=diagnosis,
                    evidence=evidence,
                    candidates=[candidate],
                    round_offset=len(all_rounds),
                )
                self._check_runtime_control()
            except NegotiationFailure as exc:
                initial_decisions.extend(exc.decisions)
                all_reviews.extend(exc.reviews)
                all_rounds.extend(exc.rounds)
                report = self._base_report(
                    run_id=run_id,
                    evidence=evidence,
                    diagnosis=diagnosis,
                    initial_decisions=initial_decisions,
                    peer_reviews=all_reviews,
                    rounds=all_rounds,
                    final_status="safe_stopped",
                    human_review_required=self.protocol.human_review_on_failure,
                )
                report["configuration_errors"] = [str(exc)]
                report["replanning_attempts"] = replanning_attempts
                return self._finalize_report(report)
            initial_decisions.extend(decisions)
            all_reviews.extend(reviews)
            all_rounds.extend(rounds)
            if selected_action is None:
                report = self._base_report(
                    run_id=run_id,
                    evidence=evidence,
                    diagnosis=diagnosis,
                    initial_decisions=initial_decisions,
                    peer_reviews=all_reviews,
                    rounds=all_rounds,
                    final_status="safe_stopped",
                    human_review_required=True,
                )
                report["replanning_attempts"] = replanning_attempts
                return self._finalize_report(report)

            last_action = selected_action
            action_error = _action_semantic_error(
                selected_action,
                protocol=self.protocol,
                evidence=evidence,
                namespace=namespace,
                deployment=deployment,
            )
            if action_error:
                last_validation = {
                    "valid": False,
                    "command": "",
                    "stderr": action_error,
                }
                self._record(
                    "safety_validations",
                    last_validation,
                    run_id,
                )
                replanning_attempts.append(
                    {
                        "failed_action": selected_action.kind.value,
                        "reason": action_error,
                        "next_step": (
                            "try_next_candidate"
                            if candidate_index + 1 < max_attempts
                            else "human_review_required"
                        ),
                    }
                )
                continue
            validation = self._validate_action(selected_action)
            last_validation = validation
            self._record("safety_validations", validation, run_id)
            self._check_runtime_control()
            if not validation["valid"]:
                report = self._base_report(
                    run_id=run_id,
                    evidence=evidence,
                    diagnosis=diagnosis,
                    initial_decisions=initial_decisions,
                    peer_reviews=all_reviews,
                    rounds=all_rounds,
                    final_status="safe_stopped",
                    human_review_required=True,
                )
                report["selected_action"] = to_serializable(selected_action)
                report["safety_validation"] = validation
                return self._finalize_report(report)

            action_id = all_rounds[-1].selected_action_id or new_trace_id("action")
            try:
                self._check_runtime_control()
                with self._operation_context(namespace, deployment):
                    execution_event = {
                        "run_id": run_id,
                        "action_id": action_id,
                        "action": to_serializable(selected_action),
                    }
                    self._record(
                        "executed_actions",
                        {
                            **execution_event,
                            "event_type": "execution_dispatched",
                        },
                        run_id,
                    )
                    execution = executor.execute_recovery(selected_action)
                    self._check_runtime_control()
                    last_execution = execution
                    self._record(
                        "executed_actions",
                        {
                            **execution_event,
                            "event_type": "execution_completed",
                            "execution_result": asdict(execution),
                        },
                        run_id,
                    )
                    if execution.valid:
                        executed_actions.append(selected_action)
                    after_evidence = self.evidence_provider.collect(
                        namespace,
                        deployment,
                    )
                    assessment = self.recovery_monitor.assess(
                        selected_action,
                        evidence,
                        after_evidence,
                        execution,
                    )
                    last_assessment = assessment.to_dict()
                    post_reviews = self._post_execution_reviews(
                        run_id=run_id,
                        action_id=action_id,
                        action=selected_action,
                        after_evidence=after_evidence,
                        execution=execution,
                        assessment=assessment,
                    )
            except OperationLockError as exc:
                report = self._base_report(
                    run_id=run_id,
                    evidence=evidence,
                    diagnosis=diagnosis,
                    initial_decisions=initial_decisions,
                    peer_reviews=all_reviews,
                    rounds=all_rounds,
                    final_status="safe_stopped",
                    human_review_required=True,
                )
                report["selected_action"] = to_serializable(selected_action)
                report["safety_validation"] = validation
                report["execution_result"] = asdict(
                    _empty_result(self.mode.value, str(exc))
                )
                return self._finalize_report(report)
            except PostReviewFailure as exc:
                all_post_reviews.extend(exc.reviews)
                report = self._base_report(
                    run_id=run_id,
                    evidence=evidence,
                    diagnosis=diagnosis,
                    initial_decisions=initial_decisions,
                    peer_reviews=all_reviews,
                    rounds=all_rounds,
                    final_status="safe_failure",
                    human_review_required=self.protocol.human_review_on_failure,
                )
                report.update(
                    {
                        "selected_action": to_serializable(selected_action),
                        "safety_validation": validation,
                        "execution_result": asdict(execution),
                        "recovery_monitoring": assessment.to_dict(),
                        "executed_actions": [
                            to_serializable(action)
                            for action in executed_actions
                        ],
                        "post_execution_reviews": [
                            to_serializable(review)
                            for review in all_post_reviews
                        ],
                        "replanning_attempts": replanning_attempts,
                        "configuration_errors": [str(exc)],
                    }
                )
                return self._finalize_report(report)

            all_post_reviews.extend(post_reviews)
            recovered = (
                execution.valid
                and assessment.recovery_success
                and all(review.approved for review in post_reviews)
            )
            if recovered:
                report = self._base_report(
                    run_id=run_id,
                    evidence=evidence,
                    diagnosis=diagnosis,
                    initial_decisions=initial_decisions,
                    peer_reviews=all_reviews,
                    rounds=all_rounds,
                    final_status=(
                        "recovered"
                        if candidate_index == 0
                        else "recovered_after_replan"
                    ),
                    human_review_required=False,
                )
                report.update(
                    {
                        "valid": True,
                        "selected_action": to_serializable(selected_action),
                        "safety_validation": validation,
                        "execution_result": asdict(execution),
                        "recovery_monitoring": assessment.to_dict(),
                        "executed_actions": [
                            to_serializable(action)
                            for action in executed_actions
                        ],
                        "post_execution_reviews": [
                            to_serializable(review)
                            for review in all_post_reviews
                        ],
                        "replanning_attempts": replanning_attempts,
                    }
                )
                return self._finalize_report(report)

            replanning_attempts.append(
                {
                    "failed_action": selected_action.kind.value,
                    "reason": (
                        assessment.remaining_problem
                        or execution.stderr
                        or "post-execution review rejected recovery"
                    ),
                    "next_step": (
                        "try_next_candidate"
                        if candidate_index + 1 < max_attempts
                        else "human_review_required"
                    ),
                }
            )

        report = self._base_report(
            run_id=run_id,
            evidence=evidence,
            diagnosis=diagnosis,
            initial_decisions=initial_decisions,
            peer_reviews=all_reviews,
            rounds=all_rounds,
            final_status="safe_failure",
            human_review_required=True,
        )
        report.update(
            {
                "selected_action": (
                    to_serializable(last_action) if last_action else {}
                ),
                "safety_validation": last_validation,
                "execution_result": asdict(last_execution),
                "recovery_monitoring": last_assessment,
                "executed_actions": [
                    to_serializable(action) for action in executed_actions
                ],
                "post_execution_reviews": [
                    to_serializable(review) for review in all_post_reviews
                ],
                "replanning_attempts": replanning_attempts,
            }
        )
        return self._finalize_report(report)

    def _negotiate(
        self,
        run_id: str,
        diagnosis: Diagnosis,
        evidence: EvidenceSnapshot,
        candidates: list[RecoveryActionCandidate],
        round_offset: int = 0,
    ) -> tuple[
        RecoveryAction | None,
        list[SupervisionDecision],
        list[PeerReview],
        list[NegotiationRound],
    ]:
        if not candidates:
            return None, [], [], []

        action = candidates[0].action
        decisions: list[SupervisionDecision] = []
        all_reviews: list[PeerReview] = []
        rounds: list[NegotiationRound] = []
        proposal_agent = self._single_adapter_for("propose").name

        for local_round in range(1, self.protocol.max_negotiation_rounds + 1):
            round_index = round_offset + local_round
            decision = SupervisionDecision(
                decision_id=new_trace_id("decision"),
                run_id=run_id,
                round_index=round_index,
                agent=proposal_agent,
                decision_type="recovery_action_proposal",
                proposed_action=action,
                approved=True,
                reason=action.reason,
                confidence=_candidate_confidence(candidates, action),
                evidence_refs=_evidence_refs(evidence, diagnosis.cause),
                reward=_candidate_reward(candidates, action),
                policy_version=self._policy_version(),
            )
            decisions.append(decision)
            self._record("initial_decisions", decision, run_id)
            try:
                reviews = self._review_application_action(
                    run_id=run_id,
                    round_index=round_index,
                    decision=decision,
                    diagnosis=diagnosis,
                    evidence=evidence,
                )
            except ReviewCollectionFailure as exc:
                all_reviews.extend(exc.reviews)
                raise NegotiationFailure(
                    str(exc),
                    decisions=decisions,
                    reviews=all_reviews,
                    rounds=rounds,
                ) from exc
            all_reviews.extend(reviews)

            abstentions = tuple(
                review.reviewer
                for review in reviews
                if review.verdict == ReviewVerdict.ABSTAIN
            )
            decision_scopes = _decision_scopes(action)
            outcome = self.consensus_resolver.resolve(
                reviews=reviews,
                profile=self.protocol,
                decision_scope=decision_scopes,
            )
            if not outcome.approved:
                round_result = NegotiationRound(
                    run_id=run_id,
                    round_index=round_index,
                    input_decision_ids=(decision.decision_id,),
                    review_ids=tuple(review.review_id for review in reviews),
                    revisions=(),
                    remaining_vetoes=outcome.blocking_vetoes,
                    remaining_abstentions=abstentions,
                    consensus_status="rejected",
                    selected_action_id=None,
                    decision_scopes=decision_scopes,
                    consensus_strategy=outcome.strategy,
                    non_blocking_objections=outcome.non_blocking_objections,
                    consensus_reason=outcome.reason,
                )
                rounds.append(round_result)
                self._record("negotiation_rounds", round_result, run_id)
                return None, decisions, all_reviews, rounds

            if outcome.revisions:
                try:
                    revised_action, revision_notes = _apply_revisions(
                        action,
                        list(outcome.revisions),
                    )
                    revision_error = _action_semantic_error(
                        revised_action,
                        protocol=self.protocol,
                        evidence=evidence,
                        namespace=evidence.namespace,
                        deployment=evidence.deployment,
                    )
                    if revision_error:
                        raise AdapterOutputError(
                            f"revised action rejected: {revision_error}"
                        )
                except Exception as exc:
                    failure_round = NegotiationRound(
                        run_id=run_id,
                        round_index=round_index,
                        input_decision_ids=(decision.decision_id,),
                        review_ids=tuple(
                            review.review_id for review in reviews
                        ),
                        revisions=(f"rejected:{exc}",),
                        remaining_vetoes=outcome.blocking_vetoes,
                        remaining_abstentions=abstentions,
                        consensus_status="revision_rejected",
                        selected_action_id=None,
                        decision_scopes=decision_scopes,
                        consensus_strategy=outcome.strategy,
                        non_blocking_objections=(
                            outcome.non_blocking_objections
                        ),
                        consensus_reason=str(exc),
                    )
                    rounds.append(failure_round)
                    self._record(
                        "negotiation_rounds",
                        failure_round,
                        run_id,
                    )
                    raise NegotiationFailure(
                        str(exc),
                        decisions=decisions,
                        reviews=all_reviews,
                        rounds=rounds,
                    ) from exc
                round_result = NegotiationRound(
                    run_id=run_id,
                    round_index=round_index,
                    input_decision_ids=(decision.decision_id,),
                    review_ids=tuple(review.review_id for review in reviews),
                    revisions=tuple(revision_notes),
                    remaining_vetoes=outcome.blocking_vetoes,
                    remaining_abstentions=abstentions,
                    consensus_status="revision_required",
                    selected_action_id=None,
                    decision_scopes=decision_scopes,
                    consensus_strategy=outcome.strategy,
                    non_blocking_objections=outcome.non_blocking_objections,
                    consensus_reason=outcome.reason,
                )
                rounds.append(round_result)
                self._record("negotiation_rounds", round_result, run_id)
                action = revised_action
                continue

            action_id = new_trace_id("action")
            round_result = NegotiationRound(
                run_id=run_id,
                round_index=round_index,
                input_decision_ids=(decision.decision_id,),
                review_ids=tuple(review.review_id for review in reviews),
                revisions=(),
                remaining_vetoes=outcome.blocking_vetoes,
                remaining_abstentions=abstentions,
                consensus_status="approved",
                selected_action_id=action_id,
                decision_scopes=decision_scopes,
                consensus_strategy=outcome.strategy,
                non_blocking_objections=outcome.non_blocking_objections,
                consensus_reason=outcome.reason,
            )
            rounds.append(round_result)
            self._record("negotiation_rounds", round_result, run_id)
            return action, decisions, all_reviews, rounds

        return None, decisions, all_reviews, rounds

    def _post_execution_reviews(
        self,
        run_id: str,
        action_id: str,
        action: RecoveryAction,
        after_evidence: EvidenceSnapshot,
        execution: CommandResult,
        assessment: RecoveryAssessment,
    ) -> list[PostExecutionReview]:
        del execution
        reviews: list[PostExecutionReview] = []
        for adapter in self.adapters.values():
            if "post_review" not in adapter.capabilities:
                continue
            try:
                review = adapter.post_review(
                    action,
                    assessment,
                    after_evidence,
                )
                if review is None:
                    continue
                normalized_review = _normalize_post_review_output(
                    adapter,
                    review,
                    run_id=run_id,
                    action_id=action_id,
                    policy_version=self._policy_version(),
                )
            except Exception as exc:
                raise PostReviewFailure(
                    f"{adapter.name} post_review failed: {exc}",
                    reviews,
                ) from exc
            reviews.append(normalized_review)
            self._record(
                "post_execution_reviews",
                normalized_review,
                run_id,
            )
        return reviews

    def _review_application_action(
        self,
        run_id: str,
        round_index: int,
        decision: SupervisionDecision,
        diagnosis: Diagnosis,
        evidence: EvidenceSnapshot,
    ) -> list[PeerReview]:
        action = decision.proposed_action
        if action is None:
            return []
        reviews: list[PeerReview] = []
        assert self.protocol is not None
        for reviewer in self.protocol.review_matrix.get(decision.agent, ()):
            adapter = self.adapters.get(reviewer)
            if adapter is None or "review" not in adapter.capabilities:
                continue
            try:
                review = adapter.review(
                    decision,
                    evidence,
                    ReviewContext(
                        run_id=run_id,
                        round_index=round_index,
                        policy_version=self.protocol.version,
                        diagnosis=diagnosis,
                    ),
                )
                if review is None:
                    continue
                normalized_review = _normalize_peer_review_output(
                    adapter,
                    review,
                    decision=decision,
                    run_id=run_id,
                    round_index=round_index,
                    policy_version=self.protocol.version,
                )
            except Exception as exc:
                raise ReviewCollectionFailure(
                    f"{adapter.name} review failed: {exc}",
                    reviews,
                ) from exc
            reviews.append(normalized_review)
            self._record("peer_reviews", normalized_review, run_id)
        return reviews

    def _validate_action(self, action: RecoveryAction) -> dict[str, Any]:
        try:
            validated = self.validator.validate_recovery_action(action)
            return {
                "valid": True,
                "command": render_recovery_command(validated),
                "stderr": "",
            }
        except (CommandValidationError, ValueError) as exc:
            return {"valid": False, "command": "", "stderr": str(exc)}

    def _base_report(
        self,
        run_id: str,
        evidence: EvidenceSnapshot,
        diagnosis: Diagnosis,
        initial_decisions: list[SupervisionDecision],
        peer_reviews: list[PeerReview],
        rounds: list[NegotiationRound],
        final_status: str,
        human_review_required: bool,
    ) -> dict[str, Any]:
        consensus = (
            rounds[-1].consensus_status
            if rounds
            else "not_required"
        )
        return {
            "command": "mutual-supervision-run",
            "valid": False,
            "mode": self.mode.value,
            "final_status": final_status,
            "run_id": run_id,
            "policy_version": self._policy_version(),
            "protocol_profile": self._protocol_identity(),
            "protocol_profile_snapshot": self._protocol_snapshot(),
            "active_agents": list(self.adapters),
            "agent_runtimes": {
                name: adapter.runtime for name, adapter in self.adapters.items()
            },
            "agent_contributions": {
                name: {
                    "decisions": 0,
                    "approvals": 0,
                    "revisions": 0,
                    "vetoes": 0,
                    "post_reviews": 0,
                    "reward": 0.0,
                }
                for name in self.adapters
            },
            "fallback_action": self.protocol.fallback_action.value,
            "configuration_errors": [],
            "evidence": evidence.to_summary(),
            "diagnosis": asdict(diagnosis),
            "initial_decisions": [
                to_serializable(decision) for decision in initial_decisions
            ],
            "peer_reviews": [
                to_serializable(review) for review in peer_reviews
            ],
            "negotiation": {
                "round_count": len(rounds),
                "rounds": [to_serializable(item) for item in rounds],
                "consensus": consensus,
                "strategy": self.protocol.consensus_strategy.value,
            },
            "selected_action": {},
            "safety_validation": {
                "valid": False,
                "command": "",
                "stderr": "no action validated",
            },
            "execution_result": asdict(
                _empty_result(self.mode.value, "no action executed")
            ),
            "recovery_monitoring": {},
            "executed_actions": [],
            "post_execution_reviews": [],
            "replanning_attempts": [],
            "human_review_required": human_review_required,
            "metadata": {
                "coordinator": "AI-MCMP",
                "controller": mutual_supervision_controller_name(
                    adapter.runtime for adapter in self.adapters.values()
                ),
                "safety": "bounded_structured_action",
                "guard_backend": self.backend.value,
                "protocol_profile": self._protocol_identity(),
                "protocol_profile_snapshot": self._protocol_snapshot(),
            },
        }

    def _protocol_identity(self) -> dict[str, str]:
        assert self.protocol is not None
        self.protocol.validate_integrity()
        return {
            "profile_id": self.protocol.profile_id,
            "version": self.protocol.version,
            "config_hash": self.protocol.config_hash,
        }

    def _begin_adapter_run(self, run_id: str) -> None:
        protocol_identity = self._protocol_identity()
        for adapter in self.adapters.values():
            begin_run = getattr(adapter, "begin_run", None)
            if callable(begin_run):
                begin_run(run_id, protocol_identity)

    def _protocol_snapshot(self) -> dict[str, Any]:
        assert self.protocol is not None
        self.protocol.validate_integrity()
        return self.protocol.to_canonical_dict()

    def _policy_version(self) -> str:
        return self.protocol.version

    def _required_capability_errors(self) -> tuple[str, ...]:
        errors = []
        for capability in ("diagnose", "propose"):
            matching = [
                adapter.name
                for adapter in self.adapters.values()
                if capability in adapter.capabilities
            ]
            if len(matching) != 1:
                errors.append(
                    f"expected exactly one active {capability} adapter; "
                    f"found {len(matching)}"
                )
        return tuple(errors)

    def _single_adapter_for(self, capability: str) -> AgentAdapter:
        return next(
            adapter
            for adapter in self.adapters.values()
            if capability in adapter.capabilities
        )

    def _configuration_failure_report(
        self,
        *,
        run_id: str,
        errors: tuple[str, ...],
    ) -> dict[str, Any]:
        return {
            "command": "mutual-supervision-run",
            "valid": False,
            "mode": self.mode.value,
            "final_status": "safe_stopped",
            "run_id": run_id,
            "policy_version": self._policy_version(),
            "protocol_profile": self._protocol_identity(),
            "protocol_profile_snapshot": self._protocol_snapshot(),
            "active_agents": list(self.adapters),
            "agent_runtimes": {
                name: adapter.runtime for name, adapter in self.adapters.items()
            },
            "agent_contributions": {
                name: {
                    "decisions": 0,
                    "approvals": 0,
                    "revisions": 0,
                    "vetoes": 0,
                    "post_reviews": 0,
                    "reward": 0.0,
                }
                for name in self.adapters
            },
            "fallback_action": self.protocol.fallback_action.value,
            "configuration_errors": list(errors),
            "evidence": {},
            "diagnosis": {},
            "initial_decisions": [],
            "peer_reviews": [],
            "negotiation": {
                "round_count": 0,
                "rounds": [],
                "consensus": "configuration_rejected",
                "strategy": self.protocol.consensus_strategy.value,
            },
            "selected_action": {},
            "safety_validation": {
                "valid": False,
                "command": "",
                "stderr": "required coordinator capability is unavailable",
            },
            "execution_result": asdict(
                _empty_result(
                    self.mode.value,
                    "required coordinator capability is unavailable",
                )
            ),
            "recovery_monitoring": {},
            "executed_actions": [],
            "post_execution_reviews": [],
            "replanning_attempts": [],
            "human_review_required": self.protocol.human_review_on_failure,
            "metadata": {
                "coordinator": "AI-MCMP",
                "controller": mutual_supervision_controller_name(
                    adapter.runtime for adapter in self.adapters.values()
                ),
                "safety": "bounded_structured_action",
                "guard_backend": self.backend.value,
                "protocol_profile": self._protocol_identity(),
                "protocol_profile_snapshot": self._protocol_snapshot(),
            },
        }

    def _finalize_report(self, report: dict[str, Any]) -> dict[str, Any]:
        report["agent_contributions"] = _agent_contributions(
            report,
            tuple(self.adapters),
        )
        if self.event_store is None:
            return report

        for agent, contribution in report["agent_contributions"].items():
            self._record(
                "agent_contributions",
                {
                    "run_id": report["run_id"],
                    "agent": agent,
                    **contribution,
                },
                report["run_id"],
            )
        if getattr(self.event_store, "defer_finalization", False):
            return report
        artifacts = self.event_store.finalize(report)
        if artifacts:
            report["artifacts"] = artifacts
        return report

    def _record(self, stream: str, value: Any, run_id: str) -> None:
        if self.event_store is not None:
            event = to_serializable(value)
            if isinstance(event, dict):
                event = {
                    **event,
                    "run_id": run_id,
                    "policy_version": self.protocol.version,
                    "protocol_profile": self._protocol_identity(),
                    "protocol_profile_snapshot": self._protocol_snapshot(),
                    "active_agents": list(self.adapters),
                    "agent_runtimes": {
                        name: adapter.runtime
                        for name, adapter in self.adapters.items()
                    },
                }
            self.event_store.append(stream, event)

    def _operation_context(
        self,
        namespace: str,
        deployment: str,
    ) -> AbstractContextManager[Any]:
        if self.mode != ExecutionMode.REAL or self.operation_lock_owned_externally:
            return nullcontext()
        return TargetOperationLock(
            namespace=namespace,
            deployment=deployment,
            lock_dir=self.operation_lock_dir,
        )

    def _check_runtime_control(self) -> None:
        if self.runtime_control is not None:
            self.runtime_control.check()


def _normalize_diagnosis_output(
    adapter: AgentAdapter,
    result: Any,
    *,
    run_id: str,
    round_index: int,
    policy_version: str,
    evidence_refs: tuple[str, ...],
    expected_service: str,
) -> tuple[Diagnosis, SupervisionDecision]:
    if (
        not isinstance(result, tuple)
        or len(result) != 2
        or not isinstance(result[0], Diagnosis)
        or not isinstance(result[1], SupervisionDecision)
    ):
        raise AdapterOutputError(
            f"{adapter.name} diagnosis output must be "
            "(Diagnosis, SupervisionDecision)"
        )
    diagnosis, decision = result
    if diagnosis.service != expected_service:
        raise AdapterOutputError(
            f"{adapter.name} diagnosis service does not match the run target"
        )
    _require_output_text(
        diagnosis.cause,
        f"{adapter.name} diagnosis cause",
    )
    _require_output_text(
        diagnosis.severity,
        f"{adapter.name} diagnosis severity",
    )
    _require_output_confidence(
        diagnosis.confidence,
        f"{adapter.name} diagnosis confidence",
    )
    if not isinstance(diagnosis.evidence, dict):
        raise AdapterOutputError(
            f"{adapter.name} diagnosis evidence must be a dictionary"
        )
    if decision.agent != adapter.name:
        raise AdapterOutputError(
            f"{adapter.name} decision agent does not match adapter identity"
        )
    if not isinstance(decision.approved, bool):
        raise AdapterOutputError(
            f"{adapter.name} decision approved must be a boolean"
        )
    _require_output_text(
        decision.decision_type,
        f"{adapter.name} decision type",
    )
    _require_output_text(
        decision.reason,
        f"{adapter.name} decision reason",
    )
    _require_output_confidence(
        decision.confidence,
        f"{adapter.name} decision confidence",
    )
    if (
        isinstance(decision.reward, bool)
        or not isinstance(decision.reward, (int, float))
        or not math.isfinite(float(decision.reward))
    ):
        raise AdapterOutputError(
            f"{adapter.name} decision reward must be finite"
        )
    if decision.proposed_action is not None:
        raise AdapterOutputError(
            f"{adapter.name} diagnosis decision must not contain an action"
        )
    return diagnosis, replace(
        decision,
        decision_id=new_trace_id("decision"),
        run_id=run_id,
        round_index=round_index,
        agent=adapter.name,
        evidence_refs=evidence_refs,
        policy_version=policy_version,
    )


def _normalize_proposal_output(
    adapter: AgentAdapter,
    result: Any,
) -> tuple[RecoveryAction, ...]:
    if result is None:
        return ()
    if not isinstance(result, (list, tuple)):
        raise AdapterOutputError(
            f"{adapter.name} proposal output must be a recovery action sequence"
        )
    actions = tuple(result)
    if any(not isinstance(action, RecoveryAction) for action in actions):
        raise AdapterOutputError(
            f"{adapter.name} proposal output contains a non-RecoveryAction"
        )
    for action in actions:
        _validate_recovery_action_output(adapter, action)
    return actions


def _normalize_peer_review_output(
    adapter: AgentAdapter,
    review: Any,
    *,
    decision: SupervisionDecision,
    run_id: str,
    round_index: int,
    policy_version: str,
) -> PeerReview:
    if not isinstance(review, PeerReview):
        raise AdapterOutputError(
            f"{adapter.name} review output must be a PeerReview"
        )
    if review.reviewer != adapter.name:
        raise AdapterOutputError(
            f"{adapter.name} review reviewer does not match adapter identity"
        )
    if (
        review.target_agent != decision.agent
        or review.target_decision_id != decision.decision_id
    ):
        raise AdapterOutputError(
            f"{adapter.name} review target does not match the proposal decision"
        )
    if (
        review.suggested_action is not None
        and not isinstance(review.suggested_action, RecoveryAction)
    ):
        raise AdapterOutputError(
            f"{adapter.name} review suggestion must be a RecoveryAction"
        )
    if review.suggested_action is not None:
        _validate_recovery_action_output(
            adapter,
            review.suggested_action,
        )
    if not isinstance(review.verdict, ReviewVerdict):
        raise AdapterOutputError(
            f"{adapter.name} review verdict must be a ReviewVerdict"
        )
    _require_output_text(
        review.reason,
        f"{adapter.name} review reason",
    )
    _require_output_confidence(
        review.confidence,
        f"{adapter.name} review confidence",
    )
    return replace(
        review,
        review_id=new_trace_id("review"),
        run_id=run_id,
        round_index=round_index,
        reviewer=adapter.name,
        target_agent=decision.agent,
        target_decision_id=decision.decision_id,
        policy_version=policy_version,
    )


def _normalize_post_review_output(
    adapter: AgentAdapter,
    review: Any,
    *,
    run_id: str,
    action_id: str,
    policy_version: str,
) -> PostExecutionReview:
    if not isinstance(review, PostExecutionReview):
        raise AdapterOutputError(
            f"{adapter.name} post-review output must be a PostExecutionReview"
        )
    if review.agent != adapter.name:
        raise AdapterOutputError(
            f"{adapter.name} post-review agent does not match adapter identity"
        )
    if not isinstance(review.approved, bool):
        raise AdapterOutputError(
            f"{adapter.name} post-review approved must be a boolean"
        )
    _require_output_text(
        review.reason,
        f"{adapter.name} post-review reason",
    )
    _require_output_confidence(
        review.confidence,
        f"{adapter.name} post-review confidence",
    )
    return replace(
        review,
        review_id=new_trace_id("post-review"),
        run_id=run_id,
        agent=adapter.name,
        action_id=action_id,
        policy_version=policy_version,
    )


def _target_alignment_error(
    action: RecoveryAction,
    *,
    namespace: str,
    deployment: str,
) -> str:
    if action.namespace == namespace and action.deployment == deployment:
        return ""
    return (
        "target mismatch: expected "
        f"{namespace}/{deployment}, got "
        f"{action.namespace}/{action.deployment}"
    )


def _action_semantic_error(
    action: RecoveryAction,
    *,
    protocol: ResearchProtocolProfile,
    evidence: EvidenceSnapshot,
    namespace: str,
    deployment: str,
) -> str:
    target_error = _target_alignment_error(
        action,
        namespace=namespace,
        deployment=deployment,
    )
    if target_error:
        return target_error
    if action.kind not in protocol.action_space:
        return (
            f"{action.kind.value} action is outside the protocol action space"
        )
    if action.kind is RecoveryActionKind.SCALE_OUT:
        if (
            isinstance(action.replicas, bool)
            or not isinstance(action.replicas, int)
        ):
            return "scale_out replicas must be an integer"
        if action.replicas <= evidence.desired_replicas:
            return (
                "scale_out replicas must be strictly greater than observed "
                f"desired replicas ({evidence.desired_replicas})"
            )
    return ""


def _validate_recovery_action_output(
    adapter: AgentAdapter,
    action: RecoveryAction,
) -> None:
    _require_output_text(
        action.namespace,
        f"{adapter.name} action namespace",
    )
    _require_output_text(
        action.deployment,
        f"{adapter.name} action deployment",
    )
    if not isinstance(action.kind, RecoveryActionKind):
        raise AdapterOutputError(
            f"{adapter.name} action kind must be a RecoveryActionKind"
        )
    if (
        action.replicas is not None
        and (
            isinstance(action.replicas, bool)
            or not isinstance(action.replicas, int)
        )
    ):
        raise AdapterOutputError(
            f"{adapter.name} action replicas must be an integer or null"
        )
    if not isinstance(action.reason, str):
        raise AdapterOutputError(
            f"{adapter.name} action reason must be text"
        )


def _require_output_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AdapterOutputError(f"{label} must not be empty")


def _require_output_confidence(value: Any, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise AdapterOutputError(f"{label} must be between 0 and 1")


def _profile_with_legacy_policy(
    profile: ResearchProtocolProfile,
    policy: MutualSupervisionPolicy,
) -> ResearchProtocolProfile:
    source = profile.to_canonical_dict()
    source.pop("config_hash")
    source.update(
        {
            "version": policy.version,
            "review_matrix": {
                target: list(reviewers)
                for target, reviewers in policy.review_matrix.items()
            },
            "max_negotiation_rounds": policy.max_negotiation_rounds,
            "max_replan_attempts": policy.max_replan_attempts,
            "fallback_action": policy.fallback_action.value,
        }
    )
    return ResearchProtocolProfile.from_dict(source)


def _apply_revisions(
    action: RecoveryAction,
    reviews: list[PeerReview],
) -> tuple[RecoveryAction, list[str]]:
    suggestions = [
        review.suggested_action
        for review in reviews
        if review.suggested_action is not None
    ]
    if not suggestions:
        return action, []
    cross_kind = [
        suggestion
        for suggestion in suggestions
        if suggestion.kind is not action.kind
    ]
    if cross_kind:
        raise AdapterOutputError(
            "cross-kind revision is not allowed: "
            f"{action.kind.value}->{cross_kind[0].kind.value}"
        )
    if action.kind == RecoveryActionKind.SCALE_OUT:
        if any(
            isinstance(suggestion.replicas, bool)
            or not isinstance(suggestion.replicas, int)
            for suggestion in suggestions
        ):
            raise AdapterOutputError(
                "scale_out revision replicas must be integers"
            )
        replicas = min(
            suggestion.replicas
            for suggestion in suggestions
        )
        revised = replace(
            action,
            replicas=replicas,
            reason=suggestions[0].reason,
        )
        return revised, [f"replicas:{action.replicas}->{replicas}"]
    return suggestions[0], [f"{action.kind.value}:reviewer_revision"]


def _decision_scopes(action: RecoveryAction) -> tuple[str, ...]:
    return {
        RecoveryActionKind.OBSERVE_ONLY: (
            "action_validity",
            "target_alignment",
            "availability",
        ),
        RecoveryActionKind.ROLLOUT_RESTART: (
            "action_validity",
            "target_alignment",
            "availability",
            "recovery",
            "executability",
        ),
        RecoveryActionKind.SCALE_OUT: (
            "action_validity",
            "target_alignment",
            "capacity",
            "resource_safety",
            "budget",
            "cost_efficiency",
        ),
    }[action.kind]


def _candidate_confidence(
    candidates: list[RecoveryActionCandidate],
    action: RecoveryAction,
) -> float:
    for candidate in candidates:
        if candidate.action.kind == action.kind:
            return candidate.confidence
    return 0.5


def _candidate_reward(
    candidates: list[RecoveryActionCandidate],
    action: RecoveryAction,
) -> float:
    for candidate in candidates:
        if candidate.action.kind == action.kind:
            return candidate.priority
    return 0.0


def _agent_contributions(
    report: dict[str, Any],
    active_agents: tuple[str, ...],
) -> dict[str, dict[str, int | float]]:
    contributions: dict[str, dict[str, int | float]] = {
        name: {
            "decisions": 0,
            "approvals": 0,
            "revisions": 0,
            "vetoes": 0,
            "post_reviews": 0,
            "reward": 0.0,
        }
        for name in active_agents
    }
    reward_samples: dict[str, list[float]] = {
        name: [] for name in active_agents
    }

    for decision in report.get("initial_decisions") or ():
        agent = decision.get("agent")
        if agent not in contributions:
            continue
        contributions[agent]["decisions"] += 1
        reward_samples[agent].append(float(decision.get("reward", 0.0)))

    verdict_fields = {
        "approve": "approvals",
        "revise": "revisions",
        "veto": "vetoes",
    }
    for review in report.get("peer_reviews") or ():
        agent = review.get("reviewer")
        if agent not in contributions:
            continue
        field_name = verdict_fields.get(review.get("verdict"))
        if field_name is not None:
            contributions[agent][field_name] += 1
        reward_samples[agent].append(float(review.get("confidence", 0.0)))

    for review in report.get("post_execution_reviews") or ():
        agent = review.get("agent")
        if agent not in contributions:
            continue
        contributions[agent]["post_reviews"] += 1
        reward_samples[agent].append(float(review.get("confidence", 0.0)))

    for agent, samples in reward_samples.items():
        if samples:
            contributions[agent]["reward"] = round(
                sum(samples) / len(samples),
                6,
            )
    return contributions


def _evidence_refs(
    evidence: EvidenceSnapshot,
    signal: str,
) -> tuple[str, ...]:
    return (
        f"evidence_source:{evidence.source}",
        f"signal:{signal}",
        f"desired_replicas:{evidence.desired_replicas}",
        f"available_replicas:{evidence.available_replicas}",
    )


def _empty_result(mode: str, stderr: str) -> CommandResult:
    return CommandResult(
        command="",
        mode=mode,
        valid=False,
        stdout="",
        stderr=stderr,
    )

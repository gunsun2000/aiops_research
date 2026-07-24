from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from aiops_k8s_agents.application_agent import AIApplicationManagementAgent
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
from aiops_k8s_agents.validator import (
    CommandValidationError,
    CommandValidator,
    render_recovery_command,
)


@dataclass
class MutualSupervisionCoordinator:
    validator: CommandValidator
    evidence_provider: EvidenceProvider
    recovery_monitor: RecoveryMonitor
    policy: MutualSupervisionPolicy
    mode: ExecutionMode = ExecutionMode.MOCK
    backend: ExecutionBackend = ExecutionBackend.PYTHON
    ha_agent: AIServiceHASupportAgent = field(default_factory=AIServiceHASupportAgent)
    app_agent: AIApplicationManagementAgent = field(
        default_factory=AIApplicationManagementAgent
    )
    infra_agent: AISemiconductorInfraOpsAgent = field(
        default_factory=AISemiconductorInfraOpsAgent
    )
    cost_agent: CostOptimizationAgent = field(default_factory=CostOptimizationAgent)
    event_store: ResearchEventSink | None = None
    operation_lock_dir: str | Path | None = None

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExecutionMode(self.mode)
        if isinstance(self.backend, str):
            self.backend = ExecutionBackend(self.backend)

    def run(
        self,
        namespace: str,
        deployment: str,
        metric: str,
        threshold: float,
    ) -> dict[str, Any]:
        run_id = new_trace_id("run")
        evidence = self.evidence_provider.collect(namespace, deployment)
        self._record("evidence", evidence.to_summary())
        diagnosis, ha_decision = self.ha_agent.diagnose_evidence(
            evidence=evidence,
            metric=metric,
            threshold=threshold,
        )
        initial_decisions = [
            SupervisionDecision(
                decision_id=new_trace_id("decision"),
                run_id=run_id,
                round_index=0,
                agent=self.ha_agent.name,
                decision_type="ha_diagnosis",
                proposed_action=None,
                approved=ha_decision.approved,
                reason=ha_decision.reason,
                confidence=diagnosis.confidence,
                evidence_refs=_evidence_refs(evidence, metric),
                reward=ha_decision.reward,
                policy_version=self.policy.version,
            )
        ]
        self._record("initial_decisions", initial_decisions[0])

        if not ha_decision.approved:
            return self._finalize_report(
                self._base_report(
                    run_id=run_id,
                    evidence=evidence,
                    diagnosis=diagnosis,
                    initial_decisions=initial_decisions,
                    peer_reviews=[],
                    rounds=[],
                    final_status="no_action_required",
                    human_review_required=False,
                )
            )

        candidates = self.app_agent.generate_recovery_candidates(
            namespace=namespace,
            deployment=deployment,
            diagnosis=diagnosis,
            evidence=evidence,
        )
        executor = KubernetesExecutor(
            validator=self.validator,
            mode=self.mode,
            backend=self.backend,
        )
        all_reviews: list[PeerReview] = []
        all_rounds: list[NegotiationRound] = []
        all_post_reviews: list[PostExecutionReview] = []
        executed_actions: list[RecoveryAction] = []
        replanning_attempts: list[dict[str, Any]] = []
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
            self.policy.max_replan_attempts + 1,
        )
        for candidate_index, candidate in enumerate(candidates[:max_attempts]):
            selected_action, decisions, reviews, rounds = self._negotiate(
                run_id=run_id,
                diagnosis=diagnosis,
                evidence=evidence,
                candidates=[candidate],
                round_offset=len(all_rounds),
            )
            initial_decisions.extend(decisions)
            all_reviews.extend(reviews)
            all_rounds.extend(rounds)
            if selected_action is None:
                return self._finalize_report(
                    self._base_report(
                        run_id=run_id,
                        evidence=evidence,
                        diagnosis=diagnosis,
                        initial_decisions=initial_decisions,
                        peer_reviews=all_reviews,
                        rounds=all_rounds,
                        final_status="safe_stopped",
                        human_review_required=True,
                    )
                )

            last_action = selected_action
            validation = self._validate_action(selected_action)
            last_validation = validation
            self._record("safety_validations", validation)
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
                    )
                    execution = executor.execute_recovery(selected_action)
                    last_execution = execution
                    self._record(
                        "executed_actions",
                        {
                            **execution_event,
                            "event_type": "execution_completed",
                            "execution_result": asdict(execution),
                        },
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

            all_post_reviews.extend(post_reviews)
            for post_review in post_reviews:
                self._record("post_execution_reviews", post_review)
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

        for local_round in range(1, self.policy.max_negotiation_rounds + 1):
            round_index = round_offset + local_round
            decision = SupervisionDecision(
                decision_id=new_trace_id("decision"),
                run_id=run_id,
                round_index=round_index,
                agent=self.app_agent.name,
                decision_type="recovery_action_proposal",
                proposed_action=action,
                approved=True,
                reason=action.reason,
                confidence=_candidate_confidence(candidates, action),
                evidence_refs=_evidence_refs(evidence, diagnosis.cause),
                reward=_candidate_reward(candidates, action),
                policy_version=self.policy.version,
            )
            decisions.append(decision)
            self._record("initial_decisions", decision)
            reviews = self._review_application_action(
                run_id=run_id,
                round_index=round_index,
                decision=decision,
                diagnosis=diagnosis,
                evidence=evidence,
            )
            all_reviews.extend(reviews)
            for review in reviews:
                self._record("peer_reviews", review)

            vetoes = tuple(
                review.reviewer
                for review in reviews
                if review.verdict == ReviewVerdict.VETO
            )
            abstentions = tuple(
                review.reviewer
                for review in reviews
                if review.verdict == ReviewVerdict.ABSTAIN
            )
            revisions = [
                review
                for review in reviews
                if review.verdict == ReviewVerdict.REVISE
            ]
            if vetoes or abstentions:
                round_result = NegotiationRound(
                        run_id=run_id,
                        round_index=round_index,
                        input_decision_ids=(decision.decision_id,),
                        review_ids=tuple(review.review_id for review in reviews),
                        revisions=(),
                        remaining_vetoes=vetoes,
                        remaining_abstentions=abstentions,
                        consensus_status="rejected",
                        selected_action_id=None,
                    )
                rounds.append(round_result)
                self._record("negotiation_rounds", round_result)
                return None, decisions, all_reviews, rounds

            if revisions:
                revised_action, revision_notes = _apply_revisions(action, revisions)
                round_result = NegotiationRound(
                        run_id=run_id,
                        round_index=round_index,
                        input_decision_ids=(decision.decision_id,),
                        review_ids=tuple(review.review_id for review in reviews),
                        revisions=tuple(revision_notes),
                        remaining_vetoes=(),
                        remaining_abstentions=(),
                        consensus_status="revision_required",
                        selected_action_id=None,
                    )
                rounds.append(round_result)
                self._record("negotiation_rounds", round_result)
                action = revised_action
                continue

            action_id = new_trace_id("action")
            round_result = NegotiationRound(
                    run_id=run_id,
                    round_index=round_index,
                    input_decision_ids=(decision.decision_id,),
                    review_ids=tuple(review.review_id for review in reviews),
                    revisions=(),
                    remaining_vetoes=(),
                    remaining_abstentions=(),
                    consensus_status="approved",
                    selected_action_id=action_id,
                )
            rounds.append(round_result)
            self._record("negotiation_rounds", round_result)
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
        infra_safe = (
            after_evidence.desired_replicas
            <= self.infra_agent.max_recommended_replicas
        )
        cost_safe = (
            action.kind != RecoveryActionKind.SCALE_OUT
            or (action.replicas or 0) <= self.cost_agent.max_cost_safe_replicas
        )
        reviews = [
            (
                self.ha_agent.name,
                assessment.recovery_success,
                (
                    "Recovery monitor confirms service recovery."
                    if assessment.recovery_success
                    else assessment.remaining_problem
                ),
                0.92 if assessment.recovery_success else 0.40,
                ("recovery_monitor", "availability"),
            ),
            (
                self.app_agent.name,
                execution.valid,
                (
                    "Kubernetes application action completed successfully."
                    if execution.valid
                    else execution.stderr or "Kubernetes action failed."
                ),
                0.95 if execution.valid else 0.30,
                ("execution_result", "deployment_status"),
            ),
            (
                self.infra_agent.name,
                infra_safe,
                (
                    "Post-execution replica state remains within infrastructure policy."
                    if infra_safe
                    else "Post-execution replica state exceeds infrastructure policy."
                ),
                0.90,
                (
                    f"desired_replicas:{after_evidence.desired_replicas}",
                    f"infra_max_replicas:{self.infra_agent.max_recommended_replicas}",
                ),
            ),
            (
                self.cost_agent.name,
                cost_safe,
                (
                    "Post-execution action remains within cost policy."
                    if cost_safe
                    else "Post-execution action exceeds cost policy."
                ),
                0.88,
                (
                    f"action_replicas:{action.replicas}",
                    f"cost_max_replicas:{self.cost_agent.max_cost_safe_replicas}",
                ),
            ),
        ]
        return [
            PostExecutionReview(
                review_id=new_trace_id("post-review"),
                run_id=run_id,
                agent=agent,
                action_id=action_id,
                approved=approved,
                reason=reason,
                confidence=confidence,
                evidence_refs=tuple(evidence_refs),
                policy_version=self.policy.version,
            )
            for agent, approved, reason, confidence, evidence_refs in reviews
        ]

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
        for reviewer in self.policy.reviewers_for(self.app_agent.name):
            if reviewer == self.ha_agent.name:
                reviews.append(
                    self._ha_review(
                        run_id,
                        round_index,
                        decision,
                        diagnosis,
                        evidence,
                    )
                )
            elif reviewer == self.infra_agent.name:
                reviews.append(
                    self._infra_review(run_id, round_index, decision, evidence)
                )
            elif reviewer == self.cost_agent.name:
                reviews.append(
                    self._cost_review(run_id, round_index, decision, evidence)
                )
        return reviews

    def _ha_review(
        self,
        run_id: str,
        round_index: int,
        decision: SupervisionDecision,
        diagnosis: Diagnosis,
        evidence: EvidenceSnapshot,
    ) -> PeerReview:
        action = decision.proposed_action
        assert action is not None
        approved = diagnosis.cause not in {"no_action_required", "unknown_metric"}
        return PeerReview(
            review_id=new_trace_id("review"),
            run_id=run_id,
            round_index=round_index,
            reviewer=self.ha_agent.name,
            target_agent=decision.agent,
            target_decision_id=decision.decision_id,
            verdict=ReviewVerdict.APPROVE if approved else ReviewVerdict.ABSTAIN,
            reason=(
                f"{action.kind.value} addresses diagnosed cause={diagnosis.cause}."
                if approved
                else "HA evidence does not justify a recovery action."
            ),
            suggested_action=None,
            confidence=diagnosis.confidence,
            evidence_refs=_evidence_refs(evidence, diagnosis.cause),
            policy_version=self.policy.version,
        )

    def _infra_review(
        self,
        run_id: str,
        round_index: int,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
    ) -> PeerReview:
        action = decision.proposed_action
        assert action is not None
        result = self.infra_agent.review(action)
        return PeerReview(
            review_id=new_trace_id("review"),
            run_id=run_id,
            round_index=round_index,
            reviewer=self.infra_agent.name,
            target_agent=decision.agent,
            target_decision_id=decision.decision_id,
            verdict=(
                ReviewVerdict.APPROVE
                if result.approved
                else ReviewVerdict.VETO
            ),
            reason=result.reason,
            suggested_action=None,
            confidence=0.92 if result.approved else 0.98,
            evidence_refs=(
                f"desired_replicas:{evidence.desired_replicas}",
                f"infra_max_replicas:{self.infra_agent.max_recommended_replicas}",
            ),
            policy_version=self.policy.version,
        )

    def _cost_review(
        self,
        run_id: str,
        round_index: int,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
    ) -> PeerReview:
        action = decision.proposed_action
        assert action is not None
        result = self.cost_agent.review(action)
        verdict = ReviewVerdict.APPROVE
        suggested_action = None
        if not result.approved:
            if (
                action.kind == RecoveryActionKind.SCALE_OUT
                and action.replicas is not None
                and self.cost_agent.max_cost_safe_replicas >= 1
                and (
                    self.cost_agent.max_cost_safe_replicas
                    > evidence.desired_replicas
                )
                and action.replicas > self.cost_agent.max_cost_safe_replicas
            ):
                verdict = ReviewVerdict.REVISE
                suggested_action = replace(
                    action,
                    replicas=self.cost_agent.max_cost_safe_replicas,
                    reason=(
                        f"{action.reason}; revised to satisfy cost replica policy"
                    ),
                )
            else:
                verdict = ReviewVerdict.VETO
        return PeerReview(
            review_id=new_trace_id("review"),
            run_id=run_id,
            round_index=round_index,
            reviewer=self.cost_agent.name,
            target_agent=decision.agent,
            target_decision_id=decision.decision_id,
            verdict=verdict,
            reason=result.reason,
            suggested_action=suggested_action,
            confidence=0.91,
            evidence_refs=(
                f"desired_replicas:{evidence.desired_replicas}",
                f"cost_max_replicas:{self.cost_agent.max_cost_safe_replicas}",
            ),
            policy_version=self.policy.version,
        )

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
            "policy_version": self.policy.version,
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
                "controller": "mutual_supervision_deterministic",
                "safety": "bounded_structured_action",
                "guard_backend": self.backend.value,
            },
        }

    def _finalize_report(self, report: dict[str, Any]) -> dict[str, Any]:
        if self.event_store is None:
            return report

        artifacts = self.event_store.finalize(report)
        if artifacts:
            report["artifacts"] = artifacts
        return report

    def _record(self, stream: str, value: Any) -> None:
        if self.event_store is not None:
            self.event_store.append(stream, value)

    def _operation_context(
        self,
        namespace: str,
        deployment: str,
    ) -> AbstractContextManager[Any]:
        if self.mode != ExecutionMode.REAL:
            return nullcontext()
        return TargetOperationLock(
            namespace=namespace,
            deployment=deployment,
            lock_dir=self.operation_lock_dir,
        )


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
    if action.kind == RecoveryActionKind.SCALE_OUT:
        replicas = min(
            suggestion.replicas
            for suggestion in suggestions
            if suggestion.replicas is not None
        )
        revised = replace(
            action,
            replicas=replicas,
            reason=suggestions[0].reason,
        )
        return revised, [f"replicas:{action.replicas}->{replicas}"]
    return suggestions[0], [f"action:{action.kind.value}->{suggestions[0].kind.value}"]


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

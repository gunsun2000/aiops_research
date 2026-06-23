from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from aiops_k8s_agents.agent_decision import AgentDecision
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
    CandidateEvaluation,
    CommandResult,
    RecoveryAction,
    RecoveryActionCandidate,
    RecoveryActionKind,
)
from aiops_k8s_agents.recovery_monitor import RecoveryMonitor
from aiops_k8s_agents.validator import (
    CommandValidationError,
    CommandValidator,
    render_recovery_command,
)


@dataclass
class AutonomousAIOpsCoordinator:
    validator: CommandValidator
    evidence_provider: EvidenceProvider
    recovery_monitor: RecoveryMonitor
    mode: ExecutionMode = ExecutionMode.MOCK
    backend: ExecutionBackend = ExecutionBackend.PYTHON
    max_replan_attempts: int = 1
    ha_agent: AIServiceHASupportAgent = field(default_factory=AIServiceHASupportAgent)
    app_agent: AIApplicationManagementAgent = field(
        default_factory=AIApplicationManagementAgent
    )
    infra_agent: AISemiconductorInfraOpsAgent = field(
        default_factory=AISemiconductorInfraOpsAgent
    )
    cost_agent: CostOptimizationAgent = field(default_factory=CostOptimizationAgent)

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExecutionMode(self.mode)
        if isinstance(self.backend, str):
            self.backend = ExecutionBackend(self.backend)
        if self.max_replan_attempts < 0:
            raise ValueError("max_replan_attempts must be >= 0")

    def run(
        self,
        namespace: str,
        deployment: str,
        metric: str,
        threshold: float,
    ) -> dict[str, Any]:
        evidence = self.evidence_provider.collect(namespace, deployment)
        diagnosis, ha_decision = self.ha_agent.diagnose_evidence(
            evidence=evidence,
            metric=metric,
            threshold=threshold,
        )
        if not ha_decision.approved:
            return self._safe_failure_report(
                evidence=evidence,
                diagnosis=diagnosis,
                ha_decision=ha_decision,
                candidates=[],
                infra_evaluations=[],
                cost_evaluations=[],
                executed_actions=[],
                replanning_attempts=[],
                validation_result={"valid": False, "stderr": ha_decision.reason},
                execution_result=_empty_result(self.mode.value, ha_decision.reason),
                recovery_assessment={},
                recommendations=[],
                final_status="no_action_required",
            )

        candidates = self.app_agent.generate_recovery_candidates(
            namespace=namespace,
            deployment=deployment,
            diagnosis=diagnosis,
            evidence=evidence,
        )
        infra_evaluations = self.infra_agent.evaluate_candidates(candidates)
        cost_evaluations = self.cost_agent.evaluate_candidates(candidates)
        ranked_candidates = _rank_candidates(candidates, infra_evaluations, cost_evaluations)

        executor = KubernetesExecutor(
            validator=self.validator,
            mode=self.mode,
            backend=self.backend,
        )
        executed_actions: list[RecoveryAction] = []
        replanning_attempts: list[dict[str, Any]] = []
        recommendations: list[dict[str, Any]] = []
        last_validation: dict[str, Any] = {"valid": False, "stderr": "no candidate"}
        last_execution = _empty_result(self.mode.value, "no candidate executed")
        last_assessment: dict[str, Any] = {}

        for index, candidate in enumerate(ranked_candidates):
            if index > self.max_replan_attempts:
                break
            validation = self._validate_action(candidate.action)
            last_validation = validation
            if not validation["valid"]:
                replanning_attempts.append(
                    {
                        "failed_action": candidate.action.kind.value,
                        "reason": validation["stderr"],
                        "next_step": "try_next_candidate",
                    }
                )
                recommendations.append(
                    _policy_recommendation(
                        candidate.action,
                        validation["stderr"],
                        evidence,
                    )
                )
                continue

            execution = executor.execute_recovery(candidate.action)
            last_execution = execution
            executed_actions.append(candidate.action)
            after_evidence = self.evidence_provider.collect(namespace, deployment)
            assessment = self.recovery_monitor.assess(
                candidate.action,
                evidence,
                after_evidence,
                execution,
            )
            last_assessment = assessment.to_dict()
            if assessment.recovery_success:
                return {
                    "command": "autonomous-run",
                    "valid": True,
                    "mode": self.mode.value,
                    "final_status": (
                        "recovered" if not replanning_attempts else "recovered_after_replan"
                    ),
                    "collected_evidence_summary": evidence.to_summary(),
                    "diagnosis": _diagnosis_to_dict(diagnosis),
                    "ha_decision": asdict(ha_decision),
                    "generated_candidates": [_candidate_to_dict(c) for c in candidates],
                    "infra_evaluations": [_evaluation_to_dict(e) for e in infra_evaluations],
                    "cost_evaluations": [_evaluation_to_dict(e) for e in cost_evaluations],
                    "selected_action": _action_to_dict(candidate.action),
                    "validation_result": validation,
                    "execution_result": asdict(execution),
                    "recovery_monitoring": last_assessment,
                    "executed_actions": [_action_to_dict(a) for a in executed_actions],
                    "replanning_attempts": replanning_attempts,
                    "policy_update_recommendations": recommendations,
                    "metadata": {
                        "coordinator": "AI-MCMP",
                        "autonomous": "closed_loop",
                        "safety": "python_validator_and_guard_backend",
                        "guard_backend": self.backend.value,
                    },
                }

            replanning_attempts.append(
                {
                    "failed_action": candidate.action.kind.value,
                    "reason": assessment.remaining_problem,
                    "next_step": "try_next_candidate",
                }
            )
            recommendations.append(
                _policy_recommendation(
                    candidate.action,
                    assessment.remaining_problem,
                    evidence,
                )
            )

        return self._safe_failure_report(
            evidence=evidence,
            diagnosis=diagnosis,
            ha_decision=ha_decision,
            candidates=candidates,
            infra_evaluations=infra_evaluations,
            cost_evaluations=cost_evaluations,
            executed_actions=executed_actions,
            replanning_attempts=replanning_attempts,
            validation_result=last_validation,
            execution_result=last_execution,
            recovery_assessment=last_assessment,
            recommendations=recommendations,
            final_status="safe_failure",
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

    def _safe_failure_report(
        self,
        evidence: EvidenceSnapshot,
        diagnosis: Any,
        ha_decision: AgentDecision,
        candidates: list[RecoveryActionCandidate],
        infra_evaluations: list[CandidateEvaluation],
        cost_evaluations: list[CandidateEvaluation],
        executed_actions: list[RecoveryAction],
        replanning_attempts: list[dict[str, Any]],
        validation_result: dict[str, Any],
        execution_result: CommandResult,
        recovery_assessment: dict[str, Any],
        recommendations: list[dict[str, Any]],
        final_status: str,
    ) -> dict[str, Any]:
        return {
            "command": "autonomous-run",
            "valid": False,
            "mode": self.mode.value,
            "final_status": final_status,
            "collected_evidence_summary": evidence.to_summary(),
            "diagnosis": _diagnosis_to_dict(diagnosis),
            "ha_decision": asdict(ha_decision),
            "generated_candidates": [_candidate_to_dict(c) for c in candidates],
            "infra_evaluations": [_evaluation_to_dict(e) for e in infra_evaluations],
            "cost_evaluations": [_evaluation_to_dict(e) for e in cost_evaluations],
            "selected_action": {},
            "validation_result": validation_result,
            "execution_result": asdict(execution_result),
            "recovery_monitoring": recovery_assessment,
            "executed_actions": [_action_to_dict(a) for a in executed_actions],
            "replanning_attempts": replanning_attempts,
            "policy_update_recommendations": recommendations,
            "metadata": {
                "coordinator": "AI-MCMP",
                "autonomous": "closed_loop",
                "safety": "python_validator_and_guard_backend",
                "guard_backend": self.backend.value,
            },
        }


def _rank_candidates(
    candidates: list[RecoveryActionCandidate],
    infra_evaluations: list[CandidateEvaluation],
    cost_evaluations: list[CandidateEvaluation],
) -> list[RecoveryActionCandidate]:
    infra_by_kind = {evaluation.action_kind: evaluation for evaluation in infra_evaluations}
    cost_by_kind = {evaluation.action_kind: evaluation for evaluation in cost_evaluations}

    def score(candidate: RecoveryActionCandidate) -> float:
        infra = infra_by_kind[candidate.action.kind]
        cost = cost_by_kind[candidate.action.kind]
        if not infra.approved or not cost.approved:
            return -1.0
        return (
            candidate.priority * 0.35
            + candidate.confidence * 0.25
            + infra.score * 0.25
            + cost.score * 0.15
        )

    return [
        candidate
        for candidate in sorted(candidates, key=score, reverse=True)
        if score(candidate) >= 0.0
    ]


def _policy_recommendation(
    action: RecoveryAction,
    reason: str,
    evidence: EvidenceSnapshot,
) -> dict[str, Any]:
    return {
        "recommended_policy_change": (
            f"Review priority and validation policy for {action.kind.value}."
        ),
        "reason": reason,
        "evidence": evidence.to_summary(),
        "risk": "human review required before changing active policy",
        "requires_human_review": True,
    }


def _candidate_to_dict(candidate: RecoveryActionCandidate) -> dict[str, Any]:
    return {
        "action": _action_to_dict(candidate.action),
        "reason": candidate.reason,
        "expected_effect": candidate.expected_effect,
        "risk_level": candidate.risk_level,
        "estimated_cost": candidate.estimated_cost,
        "required_validation": list(candidate.required_validation),
        "confidence": candidate.confidence,
        "priority": candidate.priority,
    }


def _evaluation_to_dict(evaluation: CandidateEvaluation) -> dict[str, Any]:
    return {
        "agent": evaluation.agent,
        "action_kind": evaluation.action_kind.value,
        "approved": evaluation.approved,
        "score": evaluation.score,
        "reward": evaluation.reward,
        "reason": evaluation.reason,
        "risk": evaluation.risk,
        "blocking_reason": evaluation.blocking_reason,
    }


def _action_to_dict(action: RecoveryAction) -> dict[str, Any]:
    state_changed = action.kind != RecoveryActionKind.OBSERVE_ONLY
    return {
        "namespace": action.namespace,
        "deployment": action.deployment,
        "kind": action.kind.value,
        "replicas": action.replicas,
        "reason": action.reason,
        "state_changed": state_changed,
        "action_effect_type": (
            "kubernetes_state_change"
            if state_changed
            else "read_only_observation"
        ),
    }


def _diagnosis_to_dict(diagnosis: Any) -> dict[str, Any]:
    data = asdict(diagnosis)
    return data


def _empty_result(mode: str, stderr: str) -> CommandResult:
    return CommandResult(
        command="",
        mode=mode,
        valid=False,
        stdout="",
        stderr=stderr,
    )

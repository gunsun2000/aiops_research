from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Protocol

from aiops_k8s_agents.agent_registry import AgentRegistryError
from aiops_k8s_agents.application_agent import AIApplicationManagementAgent
from aiops_k8s_agents.cost_agent import CostOptimizationAgent
from aiops_k8s_agents.evidence import EvidenceSnapshot
from aiops_k8s_agents.ha_agent import AIServiceHASupportAgent
from aiops_k8s_agents.infra_agent import AISemiconductorInfraOpsAgent
from aiops_k8s_agents.models import Diagnosis, RecoveryAction, RecoveryActionKind
from aiops_k8s_agents.mutual_supervision_models import (
    PeerReview,
    PostExecutionReview,
    ReviewVerdict,
    SupervisionDecision,
)
from aiops_k8s_agents.recovery_monitor import RecoveryAssessment
from aiops_k8s_agents.research_protocol import (
    ProtocolAgentBinding,
    ResearchProtocolProfile,
    load_research_protocol,
)


@dataclass(frozen=True)
class ReviewContext:
    run_id: str
    round_index: int
    policy_version: str
    diagnosis: Diagnosis | None = None


class AgentAdapter(Protocol):
    name: str
    runtime: str
    capabilities: tuple[str, ...]

    def diagnose(
        self,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> tuple[Diagnosis, SupervisionDecision] | None: ...

    def propose(
        self, diagnosis: Diagnosis, evidence: EvidenceSnapshot
    ) -> tuple[RecoveryAction, ...] | None: ...

    def review(
        self,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
        context: ReviewContext,
    ) -> PeerReview | None: ...

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview | None: ...


@dataclass(frozen=True)
class DeterministicHAAdapter:
    binding: ProtocolAgentBinding
    agent: AIServiceHASupportAgent = field(default_factory=AIServiceHASupportAgent)

    @property
    def name(self) -> str:
        return self.agent.name

    @property
    def runtime(self) -> str:
        return self.binding.runtime

    @property
    def capabilities(self) -> tuple[str, ...]:
        return ("diagnose", "review", "post_review")

    def diagnose(
        self,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        if not _requested_metric_is_present(self.agent, evidence, metric):
            return _missing_metric_diagnosis(
                agent=self.agent,
                binding=self.binding,
                evidence=evidence,
                metric=metric,
            )

        diagnosis, decision = self.agent.diagnose_evidence(
            evidence=evidence,
            metric=metric,
            threshold=threshold,
        )
        return diagnosis, SupervisionDecision(
            decision_id=f"{self.name}:diagnosis",
            run_id=f"{self.name}:runtime",
            round_index=0,
            agent=self.name,
            decision_type="ha_diagnosis",
            proposed_action=None,
            approved=decision.approved,
            reason=decision.reason,
            confidence=diagnosis.confidence,
            evidence_refs=(
                f"evidence_source:{evidence.source}",
                f"signal:{metric}",
            ),
            reward=decision.reward,
            policy_version=self.runtime,
        )

    def propose(
        self, diagnosis: Diagnosis, evidence: EvidenceSnapshot
    ) -> tuple[RecoveryAction, ...] | None:
        del diagnosis, evidence
        return None

    def review(
        self,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
        context: ReviewContext,
    ) -> PeerReview | None:
        if decision.proposed_action is None:
            return None
        diagnosis = context.diagnosis
        justified = decision.approved and (
            diagnosis is None
            or diagnosis.cause not in {"no_action_required", "unknown_metric"}
        )
        return PeerReview(
            review_id=f"{decision.decision_id}:{self.name}",
            run_id=context.run_id,
            round_index=context.round_index,
            reviewer=self.name,
            target_agent=decision.agent,
            target_decision_id=decision.decision_id,
            verdict=(
                ReviewVerdict.APPROVE if justified else ReviewVerdict.ABSTAIN
            ),
            reason=(
                "Recovery action is justified by the HA diagnosis."
                if justified
                else "HA evidence does not justify a recovery action."
            ),
            suggested_action=None,
            confidence=(
                diagnosis.confidence if diagnosis is not None else decision.confidence
            ),
            evidence_refs=(
                f"evidence_source:{evidence.source}",
                f"available_replicas:{evidence.available_replicas}",
            ),
            policy_version=context.policy_version,
        )

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview | None:
        del action
        return _post_review(
            agent=self.name,
            approved=assessment.recovery_success,
            reason=(
                "Recovery monitor confirms service recovery."
                if assessment.recovery_success
                else assessment.remaining_problem
            ),
            confidence=assessment.recovery_confidence,
            evidence_refs=(
                "recovery_monitor",
                f"available_replicas:{evidence.available_replicas}",
            ),
            policy_version=self.runtime,
        )


@dataclass(frozen=True)
class DeterministicApplicationAdapter:
    binding: ProtocolAgentBinding
    agent: AIApplicationManagementAgent = field(
        default_factory=AIApplicationManagementAgent
    )

    @property
    def name(self) -> str:
        return self.agent.name

    @property
    def runtime(self) -> str:
        return self.binding.runtime

    @property
    def capabilities(self) -> tuple[str, ...]:
        return ("propose", "review", "post_review")

    def diagnose(
        self,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        del evidence, metric, threshold
        return None

    def propose(
        self, diagnosis: Diagnosis, evidence: EvidenceSnapshot
    ) -> tuple[RecoveryAction, ...]:
        candidates = self.agent.generate_recovery_candidates(
            namespace=evidence.namespace,
            deployment=evidence.deployment,
            diagnosis=diagnosis,
            evidence=evidence,
        )
        return tuple(candidate.action for candidate in candidates)

    def review(
        self,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
        context: ReviewContext,
    ) -> PeerReview | None:
        action = decision.proposed_action
        if action is None:
            return None
        target_matches = (
            action.namespace == evidence.namespace
            and action.deployment == evidence.deployment
        )
        return PeerReview(
            review_id=f"{decision.decision_id}:{self.name}",
            run_id=context.run_id,
            round_index=context.round_index,
            reviewer=self.name,
            target_agent=decision.agent,
            target_decision_id=decision.decision_id,
            verdict=(
                ReviewVerdict.APPROVE
                if target_matches
                else ReviewVerdict.VETO
            ),
            reason=(
                "Action target matches the observed application."
                if target_matches
                else "Action target does not match the observed application."
            ),
            suggested_action=None,
            confidence=0.95,
            evidence_refs=(
                f"namespace:{evidence.namespace}",
                f"deployment:{evidence.deployment}",
            ),
            policy_version=context.policy_version,
        )

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview | None:
        target_matches = (
            action.namespace == evidence.namespace
            and action.deployment == evidence.deployment
        )
        ready = (
            assessment.recovery_success
            and evidence.available_replicas >= evidence.desired_replicas
            and target_matches
        )
        return _post_review(
            agent=self.name,
            approved=ready,
            reason=(
                "Application target is ready after the recovery action."
                if ready
                else "Application target is not ready after the recovery action."
            ),
            confidence=assessment.recovery_confidence,
            evidence_refs=(
                f"desired_replicas:{evidence.desired_replicas}",
                f"available_replicas:{evidence.available_replicas}",
            ),
            policy_version=self.runtime,
        )


@dataclass(frozen=True)
class DeterministicInfrastructureAdapter:
    binding: ProtocolAgentBinding
    agent: AISemiconductorInfraOpsAgent = field(
        default_factory=AISemiconductorInfraOpsAgent
    )

    @property
    def name(self) -> str:
        return self.agent.name

    @property
    def runtime(self) -> str:
        return self.binding.runtime

    @property
    def capabilities(self) -> tuple[str, ...]:
        return ("review", "post_review")

    def diagnose(
        self,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        del evidence, metric, threshold
        return None

    def propose(
        self, diagnosis: Diagnosis, evidence: EvidenceSnapshot
    ) -> tuple[RecoveryAction, ...] | None:
        del diagnosis, evidence
        return None

    def review(
        self,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
        context: ReviewContext,
    ) -> PeerReview | None:
        if decision.proposed_action is None:
            return None
        result = self.agent.review(decision.proposed_action)
        return PeerReview(
            review_id=f"{decision.decision_id}:{self.name}",
            run_id=context.run_id,
            round_index=context.round_index,
            reviewer=self.name,
            target_agent=decision.agent,
            target_decision_id=decision.decision_id,
            verdict=(ReviewVerdict.APPROVE if result.approved else ReviewVerdict.VETO),
            reason=result.reason,
            suggested_action=None,
            confidence=0.92 if result.approved else 0.98,
            evidence_refs=(
                f"desired_replicas:{evidence.desired_replicas}",
                f"infra_max_replicas:{self.agent.max_recommended_replicas}",
            ),
            policy_version=context.policy_version,
        )

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview | None:
        del action, assessment
        safe = evidence.desired_replicas <= self.agent.max_recommended_replicas
        return _post_review(
            agent=self.name,
            approved=safe,
            reason=(
                "Post-execution replica state remains within infrastructure policy."
                if safe
                else "Post-execution replica state exceeds infrastructure policy."
            ),
            confidence=0.90,
            evidence_refs=(
                f"desired_replicas:{evidence.desired_replicas}",
                f"infra_max_replicas:{self.agent.max_recommended_replicas}",
            ),
            policy_version=self.runtime,
        )


@dataclass(frozen=True)
class DeterministicCostAdapter:
    binding: ProtocolAgentBinding
    agent: CostOptimizationAgent = field(default_factory=CostOptimizationAgent)

    @property
    def name(self) -> str:
        return self.agent.name

    @property
    def runtime(self) -> str:
        return self.binding.runtime

    @property
    def capabilities(self) -> tuple[str, ...]:
        return ("review", "post_review")

    def diagnose(
        self,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        del evidence, metric, threshold
        return None

    def propose(
        self, diagnosis: Diagnosis, evidence: EvidenceSnapshot
    ) -> tuple[RecoveryAction, ...] | None:
        del diagnosis, evidence
        return None

    def review(
        self,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
        context: ReviewContext,
    ) -> PeerReview | None:
        if decision.proposed_action is None:
            return None
        action = decision.proposed_action
        result = self.agent.review(action)
        verdict = ReviewVerdict.APPROVE
        suggested_action = None
        if not result.approved:
            if (
                action.kind is RecoveryActionKind.SCALE_OUT
                and action.replicas is not None
                and self.agent.max_cost_safe_replicas >= 1
                and self.agent.max_cost_safe_replicas > evidence.desired_replicas
                and action.replicas > self.agent.max_cost_safe_replicas
            ):
                verdict = ReviewVerdict.REVISE
                suggested_action = replace(
                    action,
                    replicas=self.agent.max_cost_safe_replicas,
                    reason=(
                        f"{action.reason}; revised to satisfy cost replica policy"
                    ),
                )
            else:
                verdict = ReviewVerdict.VETO
        return PeerReview(
            review_id=f"{decision.decision_id}:{self.name}",
            run_id=context.run_id,
            round_index=context.round_index,
            reviewer=self.name,
            target_agent=decision.agent,
            target_decision_id=decision.decision_id,
            verdict=verdict,
            reason=result.reason,
            suggested_action=suggested_action,
            confidence=0.91,
            evidence_refs=(
                f"desired_replicas:{evidence.desired_replicas}",
                f"cost_max_replicas:{self.agent.max_cost_safe_replicas}",
            ),
            policy_version=context.policy_version,
        )

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview | None:
        del assessment, evidence
        safe = (
            action.kind is not RecoveryActionKind.SCALE_OUT
            or (action.replicas or 0) <= self.agent.max_cost_safe_replicas
        )
        return _post_review(
            agent=self.name,
            approved=safe,
            reason=(
                "Post-execution action remains within cost policy."
                if safe
                else "Post-execution action exceeds cost policy."
            ),
            confidence=0.88,
            evidence_refs=(
                f"action_replicas:{action.replicas}",
                f"cost_max_replicas:{self.agent.max_cost_safe_replicas}",
            ),
            policy_version=self.runtime,
        )


def _requested_metric_is_present(
    agent: AIServiceHASupportAgent,
    evidence: EvidenceSnapshot,
    metric: str,
) -> bool:
    metric_policy = agent.policy.metric_policy_for(metric)
    normalized = metric.strip().lower().replace("-", "_")
    candidates = [normalized]
    if metric_policy is not None:
        candidates.append(metric_policy.canonical_name)
        candidates.extend(metric_policy.aliases)
    if any(
        evidence.primary_metric_value(candidate) is not None
        for candidate in candidates
    ):
        return True
    canonical = (
        metric_policy.canonical_name
        if metric_policy is not None
        else normalized
    )
    return canonical in {"availability", "restart_count"}


def _missing_metric_diagnosis(
    *,
    agent: AIServiceHASupportAgent,
    binding: ProtocolAgentBinding,
    evidence: EvidenceSnapshot,
    metric: str,
) -> tuple[Diagnosis, SupervisionDecision]:
    normalized = metric.strip().lower().replace("-", "_")
    diagnosis = Diagnosis(
        service=evidence.deployment,
        cause="unknown_metric",
        severity="info",
        confidence=0.0,
        evidence={
            "requested_metric": normalized,
            "missing_evidence": [normalized],
            "supporting_evidence": evidence.to_summary(),
            "diagnosis_reason": (
                f"requested metric {normalized!r} is absent from evidence"
            ),
        },
    )
    return diagnosis, SupervisionDecision(
        decision_id=f"{agent.name}:diagnosis",
        run_id=f"{agent.name}:runtime",
        round_index=0,
        agent=agent.name,
        decision_type="ha_diagnosis",
        proposed_action=None,
        approved=False,
        reason=diagnosis.evidence["diagnosis_reason"],
        confidence=diagnosis.confidence,
        evidence_refs=(
            f"evidence_source:{evidence.source}",
            f"signal:{normalized}",
            "metric_status:missing",
        ),
        reward=agent.policy.reward_for("ha_no_action", 0.20),
        policy_version=binding.runtime,
    )


def _post_review(
    *,
    agent: str,
    approved: bool,
    reason: str,
    confidence: float,
    evidence_refs: tuple[str, ...],
    policy_version: str,
) -> PostExecutionReview:
    return PostExecutionReview(
        review_id=f"{agent}:post-review",
        run_id=f"{agent}:runtime",
        agent=agent,
        action_id=f"{agent}:action",
        approved=approved,
        reason=reason,
        confidence=confidence,
        evidence_refs=evidence_refs,
        policy_version=policy_version,
    )


AgentAdapterFactory = Callable[[ProtocolAgentBinding], AgentAdapter]
_ADAPTER_PROTOCOL_METHODS = (
    "diagnose",
    "propose",
    "review",
    "post_review",
)


@dataclass(frozen=True)
class AgentAdapterMetadata:
    supported_runtimes: tuple[str, ...]
    capabilities: tuple[str, ...]


@dataclass
class AgentAdapterRegistry:
    factories: dict[str, AgentAdapterFactory]
    metadata: dict[str, AgentAdapterMetadata] = field(default_factory=dict)
    _validated_bindings: set[ProtocolAgentBinding] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    def register(
        self,
        implementation_id: str,
        factory: AgentAdapterFactory,
        *,
        supported_runtimes: tuple[str, ...] = (),
        capabilities: tuple[str, ...] = (),
    ) -> None:
        if implementation_id in self.factories:
            raise AgentRegistryError(f"duplicate implementation: {implementation_id}")
        self.factories[implementation_id] = factory
        self.metadata[implementation_id] = AgentAdapterMetadata(
            supported_runtimes=supported_runtimes,
            capabilities=capabilities,
        )

    def validate_profile(self, profile: ResearchProtocolProfile) -> None:
        profile.validate_integrity()
        for binding in profile.agents:
            try:
                metadata = self.metadata[binding.implementation_id]
            except KeyError as exc:
                raise AgentRegistryError(
                    f"unregistered implementation: {binding.implementation_id}"
                ) from exc
            if binding.runtime not in metadata.supported_runtimes:
                raise AgentRegistryError(
                    f"unsupported runtime: {binding.runtime} for "
                    f"{binding.implementation_id}"
                )
            if binding.enabled and binding.capabilities != metadata.capabilities:
                raise AgentRegistryError(
                    "capabilities do not match implementation metadata: "
                    + binding.implementation_id
                )
        self._validated_bindings.update(profile.agents)

    def load_validated_profile(self, path: str | Path) -> ResearchProtocolProfile:
        profile = load_research_protocol(path)
        self.validate_profile(profile)
        return profile

    def create_profile(
        self,
        profile: ResearchProtocolProfile,
    ) -> tuple[AgentAdapter, ...]:
        self.validate_profile(profile)
        return tuple(self.create(binding) for binding in profile.enabled_agents)

    def create(self, binding: ProtocolAgentBinding) -> AgentAdapter:
        if binding not in self._validated_bindings:
            raise AgentRegistryError(
                "binding must be validated as part of a profile before creation"
            )
        try:
            factory = self.factories[binding.implementation_id]
        except KeyError as exc:
            raise AgentRegistryError(
                f"unregistered implementation: {binding.implementation_id}"
            ) from exc
        adapter = factory(binding)
        self.validate_adapter(binding, adapter)
        return adapter

    @staticmethod
    def validate_adapter(
        binding: ProtocolAgentBinding,
        adapter: AgentAdapter,
    ) -> None:
        if getattr(adapter, "name", None) != binding.name:
            raise AgentRegistryError(
                f"adapter name does not match binding: {binding.name}"
            )
        if getattr(adapter, "runtime", None) != binding.runtime:
            raise AgentRegistryError(
                f"adapter runtime does not match binding: {binding.name}"
            )
        if getattr(adapter, "capabilities", None) != binding.capabilities:
            raise AgentRegistryError(
                f"adapter capabilities do not match binding: {binding.name}"
            )
        for method_name in _ADAPTER_PROTOCOL_METHODS:
            if not callable(getattr(adapter, method_name, None)):
                raise AgentRegistryError(
                    f"adapter method is not callable: "
                    f"{binding.name}.{method_name}"
                )
        for capability in binding.capabilities:
            if not callable(getattr(adapter, capability, None)):
                raise AgentRegistryError(
                    f"declared adapter capability is not callable: "
                    f"{binding.name}.{capability}"
                )


def build_default_agent_adapter_registry() -> AgentAdapterRegistry:
    registry = AgentAdapterRegistry(factories={})
    registry.register(
        "deterministic-ha",
        _build_ha_adapter,
        supported_runtimes=("deterministic",),
        capabilities=("diagnose", "review", "post_review"),
    )
    registry.register(
        "deterministic-application",
        _build_application_adapter,
        supported_runtimes=("deterministic",),
        capabilities=("propose", "review", "post_review"),
    )
    registry.register(
        "deterministic-infrastructure",
        _build_infrastructure_adapter,
        supported_runtimes=("deterministic",),
        capabilities=("review", "post_review"),
    )
    registry.register(
        "deterministic-cost",
        _build_cost_adapter,
        supported_runtimes=("deterministic",),
        capabilities=("review", "post_review"),
    )
    return registry


def _require_deterministic_runtime(binding: ProtocolAgentBinding) -> None:
    if binding.runtime != "deterministic":
        raise AgentRegistryError(f"unsupported runtime: {binding.runtime}")


def _build_ha_adapter(binding: ProtocolAgentBinding) -> AgentAdapter:
    _require_deterministic_runtime(binding)
    return DeterministicHAAdapter(binding)


def _build_application_adapter(binding: ProtocolAgentBinding) -> AgentAdapter:
    _require_deterministic_runtime(binding)
    return DeterministicApplicationAdapter(binding)


def _build_infrastructure_adapter(binding: ProtocolAgentBinding) -> AgentAdapter:
    _require_deterministic_runtime(binding)
    return DeterministicInfrastructureAdapter(binding)


def _build_cost_adapter(binding: ProtocolAgentBinding) -> AgentAdapter:
    _require_deterministic_runtime(binding)
    return DeterministicCostAdapter(binding)

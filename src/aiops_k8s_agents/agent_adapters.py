from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from aiops_k8s_agents.agent_registry import AgentRegistryError
from aiops_k8s_agents.application_agent import AIApplicationManagementAgent
from aiops_k8s_agents.cost_agent import CostOptimizationAgent
from aiops_k8s_agents.evidence import EvidenceSnapshot
from aiops_k8s_agents.ha_agent import AIServiceHASupportAgent
from aiops_k8s_agents.infra_agent import AISemiconductorInfraOpsAgent
from aiops_k8s_agents.models import Diagnosis, RecoveryAction
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


class AgentAdapter(Protocol):
    name: str
    runtime: str
    capabilities: tuple[str, ...]

    def diagnose(
        self, evidence: EvidenceSnapshot, threshold: float
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
        return ("diagnose",)

    def diagnose(
        self, evidence: EvidenceSnapshot, threshold: float
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        metrics = tuple(evidence.metric_values)
        if len(metrics) != 1:
            return None

        diagnosis, decision = self.agent.diagnose_evidence(
            evidence=evidence,
            metric=metrics[0],
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
                f"signal:{metrics[0]}",
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
        del decision, evidence, context
        return None

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview | None:
        del action, assessment, evidence
        return None


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
        return ("propose",)

    def diagnose(
        self, evidence: EvidenceSnapshot, threshold: float
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        del evidence, threshold
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
        del decision, evidence, context
        return None

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview | None:
        del action, assessment, evidence
        return None


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
        return ("review",)

    def diagnose(
        self, evidence: EvidenceSnapshot, threshold: float
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        del evidence, threshold
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
        del action, assessment, evidence
        return None


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
        return ("review",)

    def diagnose(
        self, evidence: EvidenceSnapshot, threshold: float
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        del evidence, threshold
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
        del action, assessment, evidence
        return None


AgentAdapterFactory = Callable[[ProtocolAgentBinding], AgentAdapter]


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
        return factory(binding)


def build_default_agent_adapter_registry() -> AgentAdapterRegistry:
    registry = AgentAdapterRegistry(factories={})
    registry.register(
        "deterministic-ha",
        _build_ha_adapter,
        supported_runtimes=("deterministic",),
        capabilities=("diagnose",),
    )
    registry.register(
        "deterministic-application",
        _build_application_adapter,
        supported_runtimes=("deterministic",),
        capabilities=("propose",),
    )
    registry.register(
        "deterministic-infrastructure",
        _build_infrastructure_adapter,
        supported_runtimes=("deterministic",),
        capabilities=("review",),
    )
    registry.register(
        "deterministic-cost",
        _build_cost_adapter,
        supported_runtimes=("deterministic",),
        capabilities=("review",),
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

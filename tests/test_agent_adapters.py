from dataclasses import replace
from types import SimpleNamespace

import pytest

from aiops_k8s_agents.agent_adapters import (
    AgentAdapterRegistry,
    ReviewContext,
    build_default_agent_adapter_registry,
)
from aiops_k8s_agents.agent_registry import AgentRegistryError
from aiops_k8s_agents.evidence import EvidenceSnapshot
from aiops_k8s_agents.models import RecoveryActionKind
from aiops_k8s_agents.mutual_supervision_models import SupervisionDecision
from aiops_k8s_agents.recovery_monitor import RecoveryAssessment
from aiops_k8s_agents.research_protocol import load_research_protocol
from aiops_k8s_agents.research_protocol import ResearchProtocolProfile


def test_default_adapter_registry_builds_four_agents():
    registry = build_default_agent_adapter_registry()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )

    adapters = registry.create_profile(profile)

    assert [adapter.name for adapter in adapters] == [
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    ]
    assert all(adapter.runtime == "deterministic" for adapter in adapters)


def test_unregistered_implementation_is_rejected():
    registry = build_default_agent_adapter_registry()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    binding = replace(
        profile.agents[0],
        implementation_id="not-registered",
    )

    with pytest.raises(AgentRegistryError, match="unregistered implementation"):
        registry.validate_profile(profile_with_binding(profile, binding))


def test_disabled_binding_with_unsupported_runtime_is_rejected():
    registry = build_default_agent_adapter_registry()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    binding = replace(profile.agents[0], runtime="unsupported", enabled=False)

    with pytest.raises(AgentRegistryError, match="unsupported runtime"):
        registry.validate_profile(profile_with_binding(profile, binding))


def test_enabled_binding_capabilities_must_match_adapter_metadata():
    registry = build_default_agent_adapter_registry()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    binding = replace(profile.agents[0], capabilities=("review",))

    with pytest.raises(AgentRegistryError, match="capabilities do not match"):
        registry.validate_profile(profile_with_binding(profile, binding))


def test_validated_profile_allows_direct_adapter_creation():
    registry = build_default_agent_adapter_registry()
    profile = registry.load_validated_profile(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )

    assert registry.create(profile.enabled_agents[0]).name == "AIServiceHASupportAgent"


def test_adapter_creation_requires_profile_validation():
    registry = build_default_agent_adapter_registry()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )

    with pytest.raises(
        AgentRegistryError,
        match="validated as part of a profile",
    ):
        registry.create(profile.enabled_agents[0])


def test_declared_and_unsupported_adapter_capabilities_are_explicit():
    registry = build_default_agent_adapter_registry()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    adapters = {
        adapter.name: adapter for adapter in registry.create_profile(profile)
    }
    evidence = EvidenceSnapshot(
        namespace="online-boutique",
        deployment="paymentservice",
        metric_values={"cpu": 90.0},
    )
    ha = adapters["AIServiceHASupportAgent"]
    diagnosis_result = ha.diagnose(evidence, metric="cpu", threshold=80.0)

    assert diagnosis_result is not None
    diagnosis, _ = diagnosis_result
    assert ha.propose(diagnosis, evidence) is None

    application = adapters["AIApplicationManagementAgent"]
    actions = application.propose(diagnosis, evidence)
    assert actions is not None
    assert {action.kind for action in actions} == {
        RecoveryActionKind.OBSERVE_ONLY,
        RecoveryActionKind.ROLLOUT_RESTART,
        RecoveryActionKind.SCALE_OUT,
    }

    decision = SupervisionDecision(
        decision_id="decision-1",
        run_id="run-1",
        round_index=1,
        agent=application.name,
        decision_type="recovery_action_proposal",
        proposed_action=actions[0],
        approved=True,
        reason=actions[0].reason,
        confidence=0.9,
        evidence_refs=("cpu",),
        reward=0.9,
        policy_version="test-v1",
    )
    context = ReviewContext(
        run_id="run-1",
        round_index=1,
        policy_version="test-v1",
    )

    assert application.diagnose(evidence, metric="cpu", threshold=80.0) is None
    assert application.review(decision, evidence, context) is not None
    assert ha.review(decision, evidence, context) is not None
    assert (
        adapters["AISemiconductorInfraOpsAgent"].propose(diagnosis, evidence)
        is None
    )
    assert adapters["CostOptimizationAgent"].propose(diagnosis, evidence) is None
    assert adapters["AISemiconductorInfraOpsAgent"].review(
        decision, evidence, context
    ) is not None
    assert (
        adapters["CostOptimizationAgent"].review(decision, evidence, context)
        is not None
    )

    assessment = RecoveryAssessment(
        recovery_success=True,
        metric_improvement=0.8,
        remaining_problem="",
        recovery_confidence=0.9,
        replanning_required=False,
    )
    post_reviews = [
        adapter.post_review(actions[0], assessment, evidence)
        for adapter in adapters.values()
    ]
    assert all(review is not None for review in post_reviews)
    assert {review.agent for review in post_reviews if review is not None} == set(
        adapters
    )
    assert all(review.approved for review in post_reviews if review is not None)
    assert all(
        "review" in adapter.capabilities
        and "post_review" in adapter.capabilities
        for adapter in adapters.values()
    )


def test_adapter_registry_rejects_duplicate_implementation_ids():
    registry = AgentAdapterRegistry(factories={})
    factory = lambda binding: binding

    registry.register("deterministic-test", factory)

    with pytest.raises(AgentRegistryError, match="duplicate implementation"):
        registry.register("deterministic-test", factory)


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("name", "CostOptimizationAgent", "adapter name"),
        ("runtime", "remote", "adapter runtime"),
        ("capabilities", ("diagnose",), "adapter capabilities"),
    ],
)
def test_registry_rejects_factory_adapter_identity_mismatch(
    field,
    bad_value,
    message,
):
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )
    default_registry = build_default_agent_adapter_registry()
    registry = AgentAdapterRegistry(factories={})
    for implementation_id, factory in default_registry.factories.items():
        metadata = default_registry.metadata[implementation_id]

        def checked_factory(binding, factory=factory, implementation_id=implementation_id):
            adapter = factory(binding)
            if implementation_id != "deterministic-infrastructure":
                return adapter
            values = {
                "name": adapter.name,
                "runtime": adapter.runtime,
                "capabilities": adapter.capabilities,
            }
            values[field] = bad_value
            return SimpleNamespace(**values)

        registry.register(
            implementation_id,
            checked_factory,
            supported_runtimes=metadata.supported_runtimes,
            capabilities=metadata.capabilities,
        )

    with pytest.raises(AgentRegistryError, match=message):
        registry.create_profile(profile)


def profile_with_binding(profile, replacement):
    source = profile.to_canonical_dict()
    source.pop("config_hash")
    for index, binding in enumerate(source["agents"]):
        if binding["name"] == replacement.name:
            source["agents"][index] = {
                "name": replacement.name,
                "implementation_id": replacement.implementation_id,
                "runtime": replacement.runtime,
                "enabled": replacement.enabled,
                "veto_scopes": list(replacement.veto_scopes),
                "consensus_weight": replacement.consensus_weight,
                "capabilities": list(replacement.capabilities),
            }
            break
    return ResearchProtocolProfile.from_dict(source)

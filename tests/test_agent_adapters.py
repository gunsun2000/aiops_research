import pytest

from aiops_k8s_agents.agent_adapters import (
    AgentAdapterRegistry,
    build_default_agent_adapter_registry,
)
from aiops_k8s_agents.agent_registry import AgentRegistryError
from aiops_k8s_agents.research_protocol import (
    ProtocolAgentBinding,
    load_research_protocol,
)


def test_default_adapter_registry_builds_four_agents():
    registry = build_default_agent_adapter_registry()
    profile = load_research_protocol(
        "config/protocol_profiles/four-agent-role-veto-v1.json"
    )

    adapters = [registry.create(binding) for binding in profile.enabled_agents]

    assert [adapter.name for adapter in adapters] == [
        "AIServiceHASupportAgent",
        "AIApplicationManagementAgent",
        "AISemiconductorInfraOpsAgent",
        "CostOptimizationAgent",
    ]
    assert all(adapter.runtime == "deterministic" for adapter in adapters)


def test_unregistered_implementation_is_rejected():
    registry = build_default_agent_adapter_registry()
    binding = ProtocolAgentBinding(
        name="UnknownAgent",
        implementation_id="not-registered",
        runtime="deterministic",
        enabled=True,
        veto_scopes=("availability",),
        consensus_weight=1.0,
    )

    with pytest.raises(AgentRegistryError, match="unregistered implementation"):
        registry.create(binding)


def test_adapter_registry_rejects_duplicate_implementation_ids():
    registry = AgentAdapterRegistry(factories={})
    factory = lambda binding: binding

    registry.register("deterministic-test", factory)

    with pytest.raises(AgentRegistryError, match="duplicate implementation"):
        registry.register("deterministic-test", factory)

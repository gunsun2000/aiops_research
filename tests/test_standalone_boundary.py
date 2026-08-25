from __future__ import annotations

import importlib
from pathlib import Path


def test_public_orchestrator_contract_is_importable() -> None:
    package = importlib.import_module("orchestrator_agent")

    assert package.ModelPartitionOrchestrationAgent
    assert package.PartitionExecutionPlan
    assert package.PartitionContractError
    assert package.run_partition_planning
    assert package.run_federated_coordination_planning


def test_source_has_no_recovery_framework_dependency() -> None:
    source_root = Path(__file__).parents[1] / "src" / "orchestrator_agent"
    forbidden = (
        "aiops_k8s_agents",
        "ha_agent",
        "application_agent",
        "cost_agent",
        "autogen",
        "aiopslab",
        "chaos_mesh",
    )

    violations: list[str] = []
    for path in source_root.glob("*.py"):
        content = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token in content:
                violations.append(f"{path.name}: {token}")

    assert violations == []


from __future__ import annotations

from dataclasses import dataclass

from aiops_k8s_agents.executor import KubernetesExecutor
from aiops_k8s_agents.models import CommandResult, RecoveryAction, ScaleAction


@dataclass
class ExecutorAgent:
    """Validates and executes the final Kubernetes action."""

    executor: KubernetesExecutor

    def execute(self, action: ScaleAction | RecoveryAction) -> CommandResult:
        if isinstance(action, RecoveryAction):
            return self.executor.execute_recovery(action)
        return self.executor.execute_scale(action)

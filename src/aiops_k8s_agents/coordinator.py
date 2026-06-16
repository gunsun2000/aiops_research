from __future__ import annotations

from dataclasses import dataclass, replace

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.application_agent import AIApplicationManagementAgent
from aiops_k8s_agents.cost_agent import CostOptimizationAgent
from aiops_k8s_agents.executor import (
    ExecutionBackend,
    ExecutionMode,
    KubernetesExecutor,
)
from aiops_k8s_agents.executor_agent import ExecutorAgent
from aiops_k8s_agents.ha_agent import AIServiceHASupportAgent
from aiops_k8s_agents.infra_agent import AISemiconductorInfraOpsAgent
from aiops_k8s_agents.models import AlertEvent, CommandResult
from aiops_k8s_agents.validator import CommandValidator


@dataclass
class AIMCMPCoordinator:
    """Coordinates the four research agents and emits the final Kubernetes action."""

    validator: CommandValidator
    mode: ExecutionMode = ExecutionMode.MOCK
    backend: ExecutionBackend = ExecutionBackend.PYTHON
    ha_agent: AIServiceHASupportAgent = AIServiceHASupportAgent()
    app_agent: AIApplicationManagementAgent = AIApplicationManagementAgent()
    infra_agent: AISemiconductorInfraOpsAgent = AISemiconductorInfraOpsAgent()
    cost_agent: CostOptimizationAgent = CostOptimizationAgent()

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExecutionMode(self.mode)
        if isinstance(self.backend, str):
            self.backend = ExecutionBackend(self.backend)
        self.executor_agent = ExecutorAgent(
            KubernetesExecutor(
                validator=self.validator,
                mode=self.mode,
                backend=self.backend,
            )
        )

    def run(self, alert: AlertEvent) -> CommandResult:
        diagnosis, ha_decision = self.ha_agent.diagnose(alert)
        if not ha_decision.approved:
            return self._rejected_result([ha_decision])

        action, app_decision = self.app_agent.propose(alert, diagnosis)
        infra_decision = self.infra_agent.review(action)
        cost_decision = self.cost_agent.review(action)
        decisions = [ha_decision, app_decision, infra_decision, cost_decision]

        if not all(decision.approved for decision in decisions):
            return self._rejected_result(decisions)

        result = self.executor_agent.execute(action)
        return replace(result, metadata=self._metadata("approved", decisions))

    def _rejected_result(self, decisions: list[AgentDecision]) -> CommandResult:
        return CommandResult(
            command="",
            mode=self.mode.value,
            valid=False,
            stdout="",
            stderr="; ".join(
                decision.reason for decision in decisions if not decision.approved
            ),
            metadata=self._metadata("rejected", decisions),
        )

    def _metadata(self, consensus: str, decisions: list[AgentDecision]) -> dict[str, str]:
        return {
            "coordinator": "AI-MCMP",
            "consensus": consensus,
            "agents": ",".join(
                [
                    self.ha_agent.name,
                    self.app_agent.name,
                    self.infra_agent.name,
                    self.cost_agent.name,
                ]
            ),
            "decisions": "|".join(
                f"{decision.agent}:{'approved' if decision.approved else 'rejected'}"
                for decision in decisions
            ),
            "actions": "|".join(
                f"{decision.agent}:{decision.action}" for decision in decisions
            ),
            "rewards": "|".join(
                f"{decision.agent}:{decision.reward:.2f}" for decision in decisions
            ),
            "reward_total": f"{sum(decision.reward for decision in decisions):.2f}",
        }


FourAgentPipeline = AIMCMPCoordinator

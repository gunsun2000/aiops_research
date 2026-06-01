from __future__ import annotations

from dataclasses import dataclass, field, replace

from aiops_k8s_agents.executor import ExecutionMode, KubernetesExecutor
from aiops_k8s_agents.models import AlertEvent, CommandResult, Diagnosis, ScaleAction
from aiops_k8s_agents.validator import CommandValidator


@dataclass(frozen=True)
class AgentDecision:
    agent: str
    action: str
    reward: float
    approved: bool
    reason: str
    parameters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AIServiceHASupportAgent:
    """모니터링 상태를 바탕으로 서비스 가용성 위험을 진단합니다."""

    name: str = "AIServiceHASupportAgent"

    def diagnose(self, alert: AlertEvent) -> tuple[Diagnosis, AgentDecision]:
        metric = alert.metric.lower()
        if metric == "cpu" and alert.value >= alert.threshold:
            severity = "critical" if alert.value >= 90 else "warning"
            diagnosis = Diagnosis(
                service=alert.service,
                cause="cpu_saturation",
                severity=severity,
                confidence=0.95,
            )
            return diagnosis, AgentDecision(
                agent=self.name,
                action="ha_scale_out_required",
                reward=0.90,
                approved=True,
                reason=f"{alert.service} CPU {alert.value:.1f}%가 임계치를 초과했습니다",
            )
        diagnosis = Diagnosis(
            service=alert.service,
            cause="no_action_required",
            severity="info",
            confidence=0.8,
        )
        return diagnosis, AgentDecision(
            agent=self.name,
            action="ha_no_action",
            reward=0.20,
            approved=False,
            reason=f"{alert.service}는 HA 복구 액션이 필요하지 않습니다",
        )


@dataclass(frozen=True)
class AIApplicationManagementAgent:
    """애플리케이션 워크로드의 배포 제어 액션을 생성합니다."""

    name: str = "AIApplicationManagementAgent"
    default_cpu_replicas: int = 3

    def propose(self, alert: AlertEvent, diagnosis: Diagnosis) -> tuple[ScaleAction, AgentDecision]:
        if diagnosis.cause != "cpu_saturation":
            raise ValueError(f"unsupported diagnosis for scaling: {diagnosis.cause}")
        action = ScaleAction(
            namespace=alert.namespace,
            deployment=alert.service,
            replicas=self.default_cpu_replicas,
            reason=(
                f"{diagnosis.service} {diagnosis.cause} "
                f"severity={diagnosis.severity} confidence={diagnosis.confidence:.2f}"
            ),
        )
        return action, AgentDecision(
            agent=self.name,
            action="app_scale_deployment",
            reward=0.85,
            approved=True,
            reason=f"{alert.service}를 {self.default_cpu_replicas}개 replica로 확장합니다",
        )


@dataclass(frozen=True)
class AISemiconductorInfraOpsAgent:
    """모사된 GPU/NPU 인프라 신호를 기준으로 액션 적합성을 검토합니다."""

    name: str = "AISemiconductorInfraOpsAgent"
    max_recommended_replicas: int = 5

    def review(self, action: ScaleAction) -> AgentDecision:
        if action.replicas > self.max_recommended_replicas:
            return AgentDecision(
                agent=self.name,
                action="infra_capacity_rejected",
                reward=-0.60,
                approved=False,
                reason="요청 replica 수가 인프라 권장 범위를 초과했습니다",
            )
        return AgentDecision(
            agent=self.name,
            action="infra_capacity_approved",
            reward=0.70,
            approved=True,
            reason="replica 목표가 모사된 가속기 자원 범위 안에 있습니다",
        )


@dataclass(frozen=True)
class CostOptimizationAgent:
    """실행 전 액션의 비용 영향을 검토합니다."""

    name: str = "CostOptimizationAgent"
    max_cost_safe_replicas: int = 3

    def review(self, action: ScaleAction) -> AgentDecision:
        if action.replicas > self.max_cost_safe_replicas:
            return AgentDecision(
                agent=self.name,
                action="cost_budget_rejected",
                reward=-0.70,
                approved=False,
                reason="요청 replica 수가 1차 비용 정책을 초과했습니다",
            )
        return AgentDecision(
            agent=self.name,
            action="cost_budget_approved",
            reward=0.60,
            approved=True,
            reason="replica 목표가 1차 비용 정책 범위 안에 있습니다",
        )


@dataclass
class ExecutorAgent:
    """계획된 Kubernetes 액션을 검증하고 실행합니다."""

    executor: KubernetesExecutor

    def execute(self, action: ScaleAction) -> CommandResult:
        return self.executor.execute_scale(action)


@dataclass
class AIMCMPCoordinator:
    """4개 전문 에이전트를 조율해 최종 Kubernetes 액션을 생성합니다."""

    validator: CommandValidator
    mode: ExecutionMode = ExecutionMode.MOCK
    ha_agent: AIServiceHASupportAgent = AIServiceHASupportAgent()
    app_agent: AIApplicationManagementAgent = AIApplicationManagementAgent()
    infra_agent: AISemiconductorInfraOpsAgent = AISemiconductorInfraOpsAgent()
    cost_agent: CostOptimizationAgent = CostOptimizationAgent()

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExecutionMode(self.mode)
        self.executor_agent = ExecutorAgent(
            KubernetesExecutor(validator=self.validator, mode=self.mode)
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
            stderr="; ".join(decision.reason for decision in decisions if not decision.approved),
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

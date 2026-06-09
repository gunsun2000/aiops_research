from __future__ import annotations

from dataclasses import dataclass

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.models import AlertEvent, Diagnosis


@dataclass(frozen=True)
class AIServiceHASupportAgent:
    """Detects service availability risk and decides whether HA recovery is needed."""

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
                reason=(
                    f"{alert.service} CPU {alert.value:.1f}%가 "
                    f"임계치 {alert.threshold:.1f}%를 초과하여 HA scale-out이 필요합니다."
                ),
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
            reason=f"{alert.service}는 현재 HA 복구 액션이 필요하지 않습니다.",
        )

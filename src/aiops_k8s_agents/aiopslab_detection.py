from __future__ import annotations

from dataclasses import dataclass, field

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.research_framework import referee_aiopslab_api_call


AIOPSLAB_DETECTION_AGENT_NAMES = (
    "AIServiceHASupportAgent",
    "AIApplicationManagementAgent",
    "AISemiconductorInfraOpsAgent",
    "CostOptimizationAgent",
)

ANOMALY_LOG_PATTERNS = (
    "panic:",
    "no reachable servers",
    "connection refused",
    "crashloopbackoff",
    "back-off restarting failed container",
    "error",
)


@dataclass(frozen=True)
class AIOpsLabActionDecision:
    api_call: str
    valid: bool
    has_anomaly: bool | None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class AIOpsLabDetectionPolicy:
    namespace: str
    service: str
    metrics_duration_minutes: int = 10
    _requested_logs: bool = False
    _requested_metrics: bool = False
    _has_anomaly: bool = False

    def next_action(self, observation: str) -> AIOpsLabActionDecision:
        if not self._requested_logs:
            self._requested_logs = True
            return self._decision(
                api_call=f'get_logs("{self.namespace}", "{self.service}")',
                consensus="investigating",
                has_anomaly=None,
                decisions=[
                    AgentDecision(
                        agent="AIServiceHASupportAgent",
                        action="ha_collect_logs",
                        reward=0.0,
                        approved=True,
                        reason="Collect service logs before deciding anomaly status.",
                    ),
                    AgentDecision(
                        agent="AIApplicationManagementAgent",
                        action="app_observe_service_logs",
                        reward=0.0,
                        approved=True,
                        reason="Use application logs as the first evidence source.",
                    ),
                    AgentDecision(
                        agent="AISemiconductorInfraOpsAgent",
                        action="infra_no_change",
                        reward=0.0,
                        approved=True,
                        reason="No infrastructure control action is needed yet.",
                    ),
                    AgentDecision(
                        agent="CostOptimizationAgent",
                        action="cost_no_change",
                        reward=0.0,
                        approved=True,
                        reason="Observation-only step has no additional resource cost.",
                    ),
                ],
            )

        if not self._requested_metrics:
            if _contains_anomaly(observation):
                self._has_anomaly = True
                consensus = "anomaly_detected"
                decisions = _anomaly_metric_decisions()
            else:
                consensus = "needs_metric_confirmation"
                decisions = _clean_log_metric_decisions()

            self._requested_metrics = True
            return self._decision(
                api_call=f'get_metrics("{self.namespace}", {self.metrics_duration_minutes})',
                consensus=consensus,
                has_anomaly=self._has_anomaly,
                decisions=decisions,
            )

        has_anomaly = self._has_anomaly or _contains_anomaly(observation)
        return self._decision(
            api_call=f'submit("{"Yes" if has_anomaly else "No"}")',
            consensus="approved",
            has_anomaly=has_anomaly,
            decisions=_submit_decisions(has_anomaly),
        )

    def _decision(
        self,
        api_call: str,
        consensus: str,
        has_anomaly: bool | None,
        decisions: list[AgentDecision],
    ) -> AIOpsLabActionDecision:
        referee = referee_aiopslab_api_call(
            api_call,
            namespace=self.namespace,
            service=self.service,
            metrics_duration_minutes=self.metrics_duration_minutes,
        )
        return AIOpsLabActionDecision(
            api_call=api_call,
            valid=referee.valid and all(decision.approved for decision in decisions),
            has_anomaly=has_anomaly,
            metadata=_metadata(
                consensus,
                decisions,
                phase=referee.phase,
                api_call=api_call,
                referee="approved" if referee.valid else "rejected",
                referee_reason=referee.reason,
            ),
        )


def format_aiopslab_action(api_call: str) -> str:
    return f"Action:```\n{api_call}\n```"


def _contains_anomaly(text: str) -> bool:
    normalized = text.lower()
    return any(pattern in normalized for pattern in ANOMALY_LOG_PATTERNS)


def _anomaly_metric_decisions() -> list[AgentDecision]:
    return [
        AgentDecision(
            agent="AIServiceHASupportAgent",
            action="ha_anomaly_detected",
            reward=0.0,
            approved=True,
            reason="Service logs contain a strong availability anomaly signal.",
        ),
        AgentDecision(
            agent="AIApplicationManagementAgent",
            action="app_collect_metrics",
            reward=0.0,
            approved=True,
            reason="Collect Prometheus metrics before final AIOpsLab submission.",
        ),
        AgentDecision(
            agent="AISemiconductorInfraOpsAgent",
            action="infra_dependency_failure_detected",
            reward=0.0,
            approved=True,
            reason="The service cannot reach its backing dependency.",
        ),
        AgentDecision(
            agent="CostOptimizationAgent",
            action="cost_observation_only",
            reward=0.0,
            approved=True,
            reason="Metric collection does not change cluster resource allocation.",
        ),
    ]


def _clean_log_metric_decisions() -> list[AgentDecision]:
    return [
        AgentDecision(
            agent="AIServiceHASupportAgent",
            action="ha_no_log_anomaly",
            reward=0.0,
            approved=True,
            reason="Logs do not yet show a direct availability anomaly.",
        ),
        AgentDecision(
            agent="AIApplicationManagementAgent",
            action="app_collect_metrics",
            reward=0.0,
            approved=True,
            reason="Use metrics to confirm that the service is healthy.",
        ),
        AgentDecision(
            agent="AISemiconductorInfraOpsAgent",
            action="infra_observe_only",
            reward=0.0,
            approved=True,
            reason="No infrastructure fault is confirmed from logs.",
        ),
        AgentDecision(
            agent="CostOptimizationAgent",
            action="cost_observation_only",
            reward=0.0,
            approved=True,
            reason="Metric collection is a low-cost diagnostic action.",
        ),
    ]


def _submit_decisions(has_anomaly: bool) -> list[AgentDecision]:
    return [
        AgentDecision(
            agent="AIServiceHASupportAgent",
            action="ha_submit_anomaly_yes" if has_anomaly else "ha_submit_anomaly_no",
            reward=0.0,
            approved=True,
            reason="Submit the final service anomaly decision.",
        ),
        AgentDecision(
            agent="AIApplicationManagementAgent",
            action="app_submit_detection_result",
            reward=0.0,
            approved=True,
            reason="The AIOpsLab detection task expects a Yes/No submission.",
        ),
        AgentDecision(
            agent="AISemiconductorInfraOpsAgent",
            action=(
                "infra_fault_scope_confirmed"
                if has_anomaly
                else "infra_no_fault_scope_confirmed"
            ),
            reward=0.0,
            approved=True,
            reason="The decision does not require direct infrastructure mutation.",
        ),
        AgentDecision(
            agent="CostOptimizationAgent",
            action="cost_no_remediation_cost",
            reward=0.0,
            approved=True,
            reason="Detection submission has no additional runtime cost.",
        ),
    ]


def _metadata(
    consensus: str,
    decisions: list[AgentDecision],
    *,
    phase: str,
    api_call: str,
    referee: str,
    referee_reason: str,
) -> dict[str, str]:
    return {
        "coordinator": "AI-MCMP",
        "task": "aiopslab-detection",
        "phase": phase,
        "phase_model": "detection|localization|analysis|mitigation",
        "consensus": consensus,
        "bounded_action": api_call,
        "referee": referee,
        "referee_reason": referee_reason,
        "agents": ",".join(AIOPSLAB_DETECTION_AGENT_NAMES),
        "decisions": "|".join(
            f"{decision.agent}:{'approved' if decision.approved else 'rejected'}"
            for decision in decisions
        ),
        "actions": "|".join(
            f"{decision.agent}:{decision.action}" for decision in decisions
        ),
    }

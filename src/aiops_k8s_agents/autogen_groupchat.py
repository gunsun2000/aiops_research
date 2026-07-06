from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.executor import (
    ExecutionBackend,
    ExecutionMode,
    KubernetesExecutor,
)
from aiops_k8s_agents.models import AlertEvent, CommandResult, ScaleAction
from aiops_k8s_agents.validator import CommandValidator

AUTOGEN_AGENT_NAMES = (
    "AIServiceHASupportAgent",
    "AIApplicationManagementAgent",
    "AISemiconductorInfraOpsAgent",
    "CostOptimizationAgent",
)

AUTOGEN_AGENT_ALIASES = {
    "AI HA Agent": "AIServiceHASupportAgent",
    "AI Service HA Support Agent": "AIServiceHASupportAgent",
    "HA Support Agent": "AIServiceHASupportAgent",
    "AI Application Management Agent": "AIApplicationManagementAgent",
    "Application Management Agent": "AIApplicationManagementAgent",
    "AI Semiconductor Infra Ops Agent": "AISemiconductorInfraOpsAgent",
    "Semiconductor Infra Ops Agent": "AISemiconductorInfraOpsAgent",
    "Cost Optimization Agent": "CostOptimizationAgent",
    "Cost Agent": "CostOptimizationAgent",
}

AUTOGEN_SYSTEM_MESSAGES = {
    "AIServiceHASupportAgent": (
        "You are the AI service HA support agent. Use the alert metric, value, "
        "threshold, and message to judge service availability risk and recovery "
        "urgency. Return agent=\"AIServiceHASupportAgent\" exactly. Approve only "
        "when the evidence crosses the threshold or indicates degraded service. "
        "Use action=ha_scale_out_required for scale-out-worthy saturation, "
        "action=ha_recovery_required for non-scale recovery needs, or "
        "action=ha_no_action when no recovery is justified. Return only the "
        "structured output schema."
    ),
    "AIApplicationManagementAgent": (
        "You are the AI application management automation agent. Return "
        "agent=\"AIApplicationManagementAgent\" exactly. Choose the least risky "
        "application action supported by the evidence: app_observe_only for "
        "self-healing or weak symptoms, app_rollout_restart for restart/latency/"
        "network degradation, or app_scale_deployment for clear capacity "
        "saturation. If proposing scale-out, choose replicas from severity and "
        "safety context instead of using a fixed number. Return only the "
        "structured output schema."
    ),
    "AISemiconductorInfraOpsAgent": (
        "You are the AI semiconductor infrastructure operations agent. Return "
        "agent=\"AISemiconductorInfraOpsAgent\" exactly. Review whether the "
        "proposed action fits Kubernetes replica safety, deployment safety, "
        "and infrastructure capacity constraints in the current prototype. "
        "Treat real GPU/NPU cluster scheduling as future work. Approve with "
        "infra_capacity_approved when the action is feasible; "
        "reject with infra_capacity_rejected if it would exceed safe capacity. "
        "Return only the structured output schema."
    ),
    "CostOptimizationAgent": (
        "You are the cost optimization support agent. Return "
        "agent=\"CostOptimizationAgent\" exactly. Review whether the action is "
        "cost-appropriate, avoids unnecessary replica increases, and respects "
        "budget policy. Approve with cost_budget_approved when the cost is "
        "acceptable; reject with cost_budget_rejected when the action is "
        "unnecessarily expensive or violates policy. Return only the structured "
        "output schema."
    ),
}

DecisionProvider = Callable[[AlertEvent], Awaitable[list[AgentDecision]]]


class AutoGenDecisionError(ValueError):
    """Raised when an AutoGen message cannot become a safe AgentDecision."""


def parse_autogen_decision(payload: Any, expected_agent: str) -> AgentDecision:
    data = _payload_to_dict(payload)
    raw_agent = str(data.get("agent", ""))
    agent = _normalize_agent_name(raw_agent)
    if agent != expected_agent:
        raise AutoGenDecisionError(
            f"expected decision from {expected_agent}, received {raw_agent or '<missing>'}"
        )

    parameters = {
        str(key): str(value)
        for key, value in dict(data.get("parameters") or {}).items()
    }
    return AgentDecision(
        agent=agent,
        action=str(data["action"]),
        reward=float(data["reward"]),
        approved=bool(data["approved"]),
        reason=str(data["reason"]),
        parameters=parameters,
    )


def build_autogen_task(alert: AlertEvent) -> str:
    payload = {
        "research_goal": (
            "Review the AIOps alert evidence and produce bounded Kubernetes "
            "operations decisions through the four-agent review process."
        ),
        "required_output": {
            "agent": f"one exact agent name from: {', '.join(AUTOGEN_AGENT_NAMES)}",
            "action": "bounded action name",
            "reward": "float reward",
            "approved": "boolean",
            "reason": "short evidence-based rationale",
            "parameters": (
                "include namespace, deployment, and replicas as strings; replicas "
                "is required only for scale-out but must remain a safe integer "
                "string when provided"
            ),
        },
        "alert": {
            "namespace": alert.namespace,
            "service": alert.service,
            "metric": alert.metric,
            "value": alert.value,
            "threshold": alert.threshold,
            "message": alert.message,
        },
        "allowed_scale_command": (
            "kubectl scale deployment <deployment> --replicas=<N> -n <namespace>"
        ),
        "safety_rule": (
            "Do not emit free-form shell commands. The executor will convert only "
            "structured, allowlisted actions into Kubernetes commands."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass
class AutoGenGroupChatCoordinator:
    validator: CommandValidator
    mode: ExecutionMode = ExecutionMode.MOCK
    backend: ExecutionBackend = ExecutionBackend.PYTHON
    decision_provider: DecisionProvider | None = None
    include_transcript: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.mode, str):
            self.mode = ExecutionMode(self.mode)
        if isinstance(self.backend, str):
            self.backend = ExecutionBackend(self.backend)

    async def run(self, alert: AlertEvent) -> CommandResult:
        if self.decision_provider is None:
            raise RuntimeError(
                "AutoGen decision_provider is required. Use "
                "AutoGenRoundRobinDecisionProvider with autogen extras installed."
            )

        decisions = await self.decision_provider(alert)
        decisions = _order_decisions(decisions)
        if not all(decision.approved for decision in decisions):
            return self._rejected_result(decisions)

        app_decision = _find_decision(decisions, "AIApplicationManagementAgent")
        action = _scale_action_from_app_decision(alert, app_decision)
        result = KubernetesExecutor(
            validator=self.validator,
            mode=self.mode,
            backend=self.backend,
        ).execute_scale(action)
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
        metadata = {
            "coordinator": "AI-MCMP",
            "autogen": "groupchat",
            "consensus": consensus,
            "agents": ",".join(AUTOGEN_AGENT_NAMES),
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
        if self.include_transcript:
            transcript = "\n".join(
                getattr(self.decision_provider, "transcript_lines", [])
            )
            if transcript:
                metadata["transcript"] = transcript
        return metadata


@dataclass
class AutoGenRoundRobinDecisionProvider:
    model_client: Any
    transcript_lines: list[str] = field(default_factory=list, init=False)

    async def __call__(self, alert: AlertEvent) -> list[AgentDecision]:
        team = self._build_team()
        result = await team.run(task=build_autogen_task(alert))
        self.transcript_lines = self._extract_transcript(result)
        return self._extract_decisions(result)

    def _build_team(self) -> Any:
        try:
            from autogen_agentchat.agents import AssistantAgent
            from autogen_agentchat.conditions import MaxMessageTermination
            from autogen_agentchat.messages import StructuredMessage
            from autogen_agentchat.teams import RoundRobinGroupChat
        except ImportError as exc:
            raise RuntimeError(
                "AutoGen extras are not installed. Run: "
                'python -m pip install -e ".[autogen,dev]"'
            ) from exc

        schema = _decision_schema()
        agents = [
            AssistantAgent(
                name=name,
                model_client=self.model_client,
                system_message=AUTOGEN_SYSTEM_MESSAGES[name],
                output_content_type=schema,
            )
            for name in AUTOGEN_AGENT_NAMES
        ]
        return RoundRobinGroupChat(
            agents,
            termination_condition=MaxMessageTermination(max_messages=len(agents) + 1),
            custom_message_types=[StructuredMessage[schema]],
        )

    @staticmethod
    def _extract_decisions(result: Any) -> list[AgentDecision]:
        decisions: list[AgentDecision] = []
        messages = getattr(result, "messages", [])
        for message in messages:
            source = getattr(message, "source", "")
            if source not in AUTOGEN_AGENT_NAMES:
                continue
            decisions.append(
                parse_autogen_decision(getattr(message, "content", None), source)
            )
        return _order_decisions(decisions)

    @staticmethod
    def _extract_transcript(result: Any) -> list[str]:
        transcript: list[str] = []
        messages = getattr(result, "messages", [])
        for message in messages:
            source = getattr(message, "source", "")
            if source not in AUTOGEN_AGENT_NAMES:
                continue
            try:
                data = _payload_to_dict(getattr(message, "content", None))
            except AutoGenDecisionError:
                continue
            transcript.append(
                (
                    f"{source}: action={data.get('action')} "
                    f"approved={data.get('approved')} "
                    f"reward={float(data.get('reward', 0.0)):.2f} "
                    f"reason={data.get('reason')}"
                )
            )
        return transcript


def create_openai_model_client(model: str) -> Any:
    try:
        from autogen_ext.models.openai import OpenAIChatCompletionClient
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI AutoGen extension is not installed. Run: "
            'python -m pip install -e ".[autogen,dev]"'
        ) from exc
    return OpenAIChatCompletionClient(model=model)


def _payload_to_dict(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return dict(payload.model_dump())
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        text = _strip_code_fence(payload)
        return dict(json.loads(text))
    raise AutoGenDecisionError(f"unsupported AutoGen payload type: {type(payload)!r}")


def _normalize_agent_name(agent: str) -> str:
    return AUTOGEN_AGENT_ALIASES.get(agent.strip(), agent.strip())


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _decision_schema() -> type[Any]:
    try:
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError(
            "pydantic is required for AutoGen structured output. Run: "
            'python -m pip install -e ".[autogen,dev]"'
        ) from exc

    class AutoGenActionParameters(BaseModel):
        namespace: str
        deployment: str
        replicas: str

    class AutoGenDecisionPayload(BaseModel):
        agent: str
        action: str
        reward: float
        approved: bool
        reason: str
        parameters: AutoGenActionParameters = Field(
            description="Kubernetes action parameters as string values."
        )

    return AutoGenDecisionPayload


def _order_decisions(decisions: list[AgentDecision]) -> list[AgentDecision]:
    by_agent = {decision.agent: decision for decision in decisions}
    missing = [name for name in AUTOGEN_AGENT_NAMES if name not in by_agent]
    if missing:
        raise AutoGenDecisionError(f"missing AutoGen decisions: {', '.join(missing)}")
    return [by_agent[name] for name in AUTOGEN_AGENT_NAMES]


def _find_decision(decisions: list[AgentDecision], agent: str) -> AgentDecision:
    for decision in decisions:
        if decision.agent == agent:
            return decision
    raise AutoGenDecisionError(f"missing decision from {agent}")


def _scale_action_from_app_decision(alert: AlertEvent, decision: AgentDecision) -> ScaleAction:
    if decision.action != "app_scale_deployment":
        raise AutoGenDecisionError(f"unsupported application action: {decision.action}")

    parameters = decision.parameters
    replicas_text = parameters.get("replicas", "3")
    if not replicas_text.isdecimal():
        raise AutoGenDecisionError(f"replicas must be an integer: {replicas_text}")

    return ScaleAction(
        namespace=parameters.get("namespace", alert.namespace),
        deployment=parameters.get("deployment", alert.service),
        replicas=int(replicas_text),
        reason=decision.reason,
    )

from __future__ import annotations

import asyncio
import inspect
import json
import math
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Awaitable, Callable, Mapping

from aiops_k8s_agents.agent_adapters import (
    AgentAdapterRegistry,
    ReviewContext,
    build_default_agent_adapter_registry,
)
from aiops_k8s_agents.agent_decision import AgentDecision
from aiops_k8s_agents.evidence import EvidenceSnapshot
from aiops_k8s_agents.executor import (
    ExecutionBackend,
    ExecutionMode,
    KubernetesExecutor,
)
from aiops_k8s_agents.models import (
    AlertEvent,
    CommandResult,
    Diagnosis,
    RecoveryAction,
    RecoveryActionKind,
    ScaleAction,
)
from aiops_k8s_agents.mutual_supervision_models import (
    PeerReview,
    PostExecutionReview,
    ReviewVerdict,
    SupervisionDecision,
)
from aiops_k8s_agents.recovery_monitor import RecoveryAssessment
from aiops_k8s_agents.research_protocol import ProtocolAgentBinding
from aiops_k8s_agents.validator import CommandValidator

AUTOGEN_AGENT_NAMES = (
    "AIServiceHASupportAgent",
    "AIApplicationManagementAgent",
    "AISemiconductorInfraOpsAgent",
    "CostOptimizationAgent",
)
AUTOGEN_RUNTIME = "autogen-round-robin"
AUTOGEN_IMPLEMENTATION_IDS = {
    "AIServiceHASupportAgent": "autogen-round-robin-ha",
    "AIApplicationManagementAgent": "autogen-round-robin",
    "AISemiconductorInfraOpsAgent": "autogen-round-robin-infrastructure",
    "CostOptimizationAgent": "autogen-round-robin-cost",
}
AUTOGEN_AGENT_CAPABILITIES = {
    "AIServiceHASupportAgent": ("diagnose", "review", "post_review"),
    "AIApplicationManagementAgent": ("propose", "review", "post_review"),
    "AISemiconductorInfraOpsAgent": ("review", "post_review"),
    "CostOptimizationAgent": ("review", "post_review"),
}
AUTOGEN_ACTION_APPROVAL = {
    "AIServiceHASupportAgent": {
        "ha_scale_out_required": True,
        "ha_recovery_required": True,
        "ha_no_action": False,
    },
    "AIApplicationManagementAgent": {
        "app_observe_only": True,
        "app_rollout_restart": True,
        "app_scale_deployment": True,
    },
    "AISemiconductorInfraOpsAgent": {
        "infra_capacity_approved": True,
        "infra_capacity_rejected": False,
    },
    "CostOptimizationAgent": {
        "cost_budget_approved": True,
        "cost_budget_rejected": False,
    },
}
AUTOGEN_ALLOWED_ACTIONS = {
    agent: frozenset(action_approval)
    for agent, action_approval in AUTOGEN_ACTION_APPROVAL.items()
}

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

DecisionProvider = Callable[
    [AlertEvent],
    Awaitable[list[AgentDecision]],
]


class AutoGenDecisionError(ValueError):
    """Raised when an AutoGen message cannot become a safe AgentDecision."""


def parse_autogen_decision(payload: Any, expected_agent: str) -> AgentDecision:
    data = _payload_to_dict(payload)
    normalized = dict(data)
    parameters = normalized.get("parameters")
    if parameters is None:
        parameters = {}
    if isinstance(parameters, Mapping):
        normalized_parameters = {
            str(key): str(value)
            for key, value in parameters.items()
        }
        for key in ("namespace", "deployment", "replicas"):
            normalized_parameters.setdefault(key, "")
        normalized["parameters"] = normalized_parameters
    try:
        validated = _decision_schema().model_validate(normalized)
    except Exception as exc:
        raise AutoGenDecisionError(
            f"AutoGen decision does not match the structured schema: {exc}"
        ) from exc

    data = validated.model_dump()
    raw_agent = data["agent"]
    agent = _normalize_agent_name(raw_agent)
    if agent != expected_agent:
        raise AutoGenDecisionError(
            f"expected decision from {expected_agent}, received {raw_agent or '<missing>'}"
        )
    if data["action"] not in AUTOGEN_ALLOWED_ACTIONS.get(agent, frozenset()):
        raise AutoGenDecisionError(
            f"unsupported AutoGen action for {agent}: {data['action']}"
        )
    required_approval = AUTOGEN_ACTION_APPROVAL[agent][data["action"]]
    if data["approved"] is not required_approval:
        raise AutoGenDecisionError(
            f"AutoGen action {data['action']} contradicts approved="
            f"{data['approved']}; required approved={required_approval}"
        )

    return AgentDecision(
        agent=agent,
        action=data["action"],
        reward=data["reward"],
        approved=data["approved"],
        reason=data["reason"],
        parameters=dict(data["parameters"]),
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

    def preflight(self) -> None:
        self._build_team()

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


@dataclass
class AutoGenProtocolDecisionSession:
    decision_provider: DecisionProvider
    _cache: dict[tuple[Any, ...], dict[str, AgentDecision]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _run_id: str | None = field(default=None, init=False, repr=False)
    _protocol_identity: tuple[tuple[str, str], ...] = field(
        default=(),
        init=False,
        repr=False,
    )

    def begin_run(
        self,
        run_id: str,
        protocol_identity: Mapping[str, str],
    ) -> None:
        identity = tuple(sorted(protocol_identity.items()))
        if self._run_id == run_id and self._protocol_identity == identity:
            return
        self._cache.clear()
        self._run_id = run_id
        self._protocol_identity = identity

    def decision_for(
        self,
        agent: str,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> AgentDecision:
        decisions = self._decisions_for(evidence, metric, threshold)
        try:
            return decisions[agent]
        except KeyError as exc:
            raise AutoGenDecisionError(
                f"missing AutoGen decision from {agent}"
            ) from exc

    def _decisions_for(
        self,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> dict[str, AgentDecision]:
        if self._run_id is None:
            raise AutoGenDecisionError(
                "AutoGen decision session must begin a coordinator run"
            )
        normalized_metric = _normalize_metric(metric)
        value = evidence.primary_metric_value(normalized_metric)
        if value is None:
            raise AutoGenDecisionError(
                f"missing evidence for AutoGen metric: {normalized_metric}"
            )
        key = (
            self._run_id,
            self._protocol_identity,
            json.dumps(
                evidence.to_summary(),
                sort_keys=True,
                separators=(",", ":"),
            ),
            normalized_metric,
            float(threshold),
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        alert = AlertEvent(
            namespace=evidence.namespace,
            service=evidence.deployment,
            metric=normalized_metric,
            value=float(value),
            threshold=float(threshold),
            message=evidence.log_summary or "; ".join(evidence.events),
        )
        raw_decisions = self.decision_provider(alert)
        if inspect.isawaitable(raw_decisions):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                raw_decisions = asyncio.run(raw_decisions)
            else:
                raise RuntimeError(
                    "synchronous mutual supervision cannot run an AutoGen "
                    "provider inside an active event loop"
                )
        decisions = _validate_provider_decisions(raw_decisions)
        cached = {decision.agent: decision for decision in decisions}
        self._cache[key] = cached
        return cached


@dataclass(frozen=True)
class AutoGenProtocolAdapter:
    binding: ProtocolAgentBinding
    session: AutoGenProtocolDecisionSession

    @property
    def name(self) -> str:
        return self.binding.name

    @property
    def runtime(self) -> str:
        return self.binding.runtime

    @property
    def capabilities(self) -> tuple[str, ...]:
        return self.binding.capabilities

    def begin_run(
        self,
        run_id: str,
        protocol_identity: Mapping[str, str],
    ) -> None:
        self.session.begin_run(run_id, protocol_identity)

    def diagnose(
        self,
        evidence: EvidenceSnapshot,
        metric: str,
        threshold: float,
    ) -> tuple[Diagnosis, SupervisionDecision] | None:
        if "diagnose" not in self.capabilities:
            return None
        normalized_metric = _normalize_metric(metric)
        value = evidence.primary_metric_value(normalized_metric)
        decision = self.session.decision_for(
            self.name,
            evidence,
            normalized_metric,
            threshold,
        )
        if value is None:
            raise AutoGenDecisionError(
                f"missing evidence for AutoGen metric: {normalized_metric}"
            )
        confidence = _decision_confidence(decision)
        diagnosis = Diagnosis(
            service=evidence.deployment,
            cause=(
                f"{normalized_metric}_saturation"
                if decision.approved
                else "no_action_required"
            ),
            severity=(
                "critical"
                if value >= threshold * 1.2
                else "high" if value >= threshold else "normal"
            ),
            confidence=confidence,
            evidence={
                "source": evidence.source,
                "metric": normalized_metric,
                "value": value,
                "threshold": threshold,
            },
        )
        return diagnosis, SupervisionDecision(
            decision_id=f"{self.name}:autogen-diagnosis",
            run_id=f"{self.name}:autogen-runtime",
            round_index=0,
            agent=self.name,
            decision_type="autogen_diagnosis",
            proposed_action=None,
            approved=decision.approved,
            reason=decision.reason,
            confidence=confidence,
            evidence_refs=(
                f"evidence_source:{evidence.source}",
                f"signal:{normalized_metric}",
            ),
            reward=decision.reward,
            policy_version=self.runtime,
        )

    def propose(
        self,
        diagnosis: Diagnosis,
        evidence: EvidenceSnapshot,
    ) -> tuple[RecoveryAction, ...] | None:
        if "propose" not in self.capabilities:
            return None
        metric, threshold = _diagnosis_metric_boundary(diagnosis)
        decision = self.session.decision_for(
            self.name,
            evidence,
            metric,
            threshold,
        )
        return (_recovery_action_from_decision(decision, evidence),)

    def review(
        self,
        decision: SupervisionDecision,
        evidence: EvidenceSnapshot,
        context: ReviewContext,
    ) -> PeerReview | None:
        if "review" not in self.capabilities:
            return None
        try:
            if context.diagnosis is None:
                raise AutoGenDecisionError(
                    "AutoGen review requires normalized diagnosis context"
                )
            metric, threshold = _diagnosis_metric_boundary(context.diagnosis)
            autogen_decision = self.session.decision_for(
                self.name,
                evidence,
                metric,
                threshold,
            )
            verdict = (
                ReviewVerdict.APPROVE
                if autogen_decision.approved
                else ReviewVerdict.VETO
            )
            reason = autogen_decision.reason
            confidence = _decision_confidence(autogen_decision)
        except Exception as exc:
            verdict = ReviewVerdict.ABSTAIN
            reason = f"AutoGen output rejected: {exc}"
            confidence = 0.0
        return PeerReview(
            review_id=f"{decision.decision_id}:{self.name}",
            run_id=context.run_id,
            round_index=context.round_index,
            reviewer=self.name,
            target_agent=decision.agent,
            target_decision_id=decision.decision_id,
            verdict=verdict,
            reason=reason,
            suggested_action=None,
            confidence=confidence,
            evidence_refs=(f"evidence_source:{evidence.source}",),
            policy_version=context.policy_version,
        )

    def post_review(
        self,
        action: RecoveryAction,
        assessment: RecoveryAssessment,
        evidence: EvidenceSnapshot,
    ) -> PostExecutionReview | None:
        if "post_review" not in self.capabilities:
            return None
        del action
        return PostExecutionReview(
            review_id=f"{self.name}:autogen-post-review",
            run_id=f"{self.name}:autogen-runtime",
            agent=self.name,
            action_id="pending-normalization",
            approved=assessment.recovery_success,
            reason=(
                "Recovery monitor confirms the bounded action recovered the service."
                if assessment.recovery_success
                else assessment.remaining_problem or "Recovery was not confirmed."
            ),
            confidence=assessment.recovery_confidence,
            evidence_refs=(
                "recovery_monitor",
                f"evidence_source:{evidence.source}",
            ),
            policy_version=self.runtime,
        )


def build_autogen_agent_adapter_registry(
    *,
    model_client: Any | None = None,
    decision_provider: DecisionProvider | None = None,
) -> AgentAdapterRegistry:
    registry = build_default_agent_adapter_registry()
    if model_client is not None and decision_provider is not None:
        raise ValueError("supply either model_client or decision_provider, not both")
    if decision_provider is None and model_client is not None:
        model_provider = AutoGenRoundRobinDecisionProvider(
            model_client=model_client
        )
        model_provider.preflight()
        decision_provider = model_provider
    if decision_provider is None:
        return registry

    session = AutoGenProtocolDecisionSession(decision_provider)
    for agent, implementation_id in AUTOGEN_IMPLEMENTATION_IDS.items():
        capabilities = AUTOGEN_AGENT_CAPABILITIES[agent]
        registry.register(
            implementation_id,
            lambda binding, session=session: AutoGenProtocolAdapter(
                binding=binding,
                session=session,
            ),
            supported_runtimes=(AUTOGEN_RUNTIME,),
            capabilities=capabilities,
        )
    return registry


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
        payload = payload.model_dump()
    if isinstance(payload, str):
        text = _strip_code_fence(payload)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AutoGenDecisionError(
                "AutoGen payload is not valid JSON"
            ) from exc
    if isinstance(payload, Mapping):
        return dict(payload)
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


@lru_cache(maxsize=1)
def _decision_schema() -> type[Any]:
    try:
        from pydantic import (
            BaseModel,
            ConfigDict,
            Field,
            FiniteFloat,
            StrictBool,
        )
    except ImportError as exc:
        raise RuntimeError(
            "pydantic is required for AutoGen structured output. Run: "
            'python -m pip install -e ".[autogen,dev]"'
        ) from exc

    class AutoGenActionParameters(BaseModel):
        model_config = ConfigDict(extra="forbid")

        namespace: str
        deployment: str
        replicas: str

    class AutoGenDecisionPayload(BaseModel):
        model_config = ConfigDict(
            extra="forbid",
            allow_inf_nan=False,
            str_strip_whitespace=True,
        )

        agent: str = Field(min_length=1)
        action: str = Field(min_length=1)
        reward: FiniteFloat
        approved: StrictBool
        reason: str = Field(min_length=1)
        parameters: AutoGenActionParameters = Field(
            description="Kubernetes action parameters as string values."
        )

    return AutoGenDecisionPayload


def _order_decisions(decisions: list[AgentDecision]) -> list[AgentDecision]:
    if len({decision.agent for decision in decisions}) != len(decisions):
        raise AutoGenDecisionError("duplicate AutoGen agent decisions")
    by_agent = {decision.agent: decision for decision in decisions}
    missing = [name for name in AUTOGEN_AGENT_NAMES if name not in by_agent]
    if missing:
        raise AutoGenDecisionError(f"missing AutoGen decisions: {', '.join(missing)}")
    unknown = sorted(set(by_agent) - set(AUTOGEN_AGENT_NAMES))
    if unknown:
        raise AutoGenDecisionError(
            f"unknown AutoGen decisions: {', '.join(unknown)}"
        )
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


def _validate_provider_decisions(payload: Any) -> list[AgentDecision]:
    if not isinstance(payload, (list, tuple)):
        raise AutoGenDecisionError(
            "AutoGen provider must return a decision sequence"
        )
    decisions: list[AgentDecision] = []
    for item in payload:
        if isinstance(item, AgentDecision):
            source: Any = {
                "agent": item.agent,
                "action": item.action,
                "reward": item.reward,
                "approved": item.approved,
                "reason": item.reason,
                "parameters": item.parameters,
            }
        else:
            source = item
        data = _payload_to_dict(source)
        raw_agent = str(data.get("agent", ""))
        expected_agent = _normalize_agent_name(raw_agent)
        if expected_agent not in AUTOGEN_AGENT_NAMES:
            raise AutoGenDecisionError(
                f"unknown AutoGen agent identity: {raw_agent or '<missing>'}"
            )
        decisions.append(parse_autogen_decision(data, expected_agent))
    return _order_decisions(decisions)


def _normalize_metric(metric: str) -> str:
    return metric.strip().lower().replace("-", "_")


def _decision_confidence(decision: AgentDecision) -> float:
    if not math.isfinite(decision.reward):
        raise AutoGenDecisionError("AutoGen reward must be finite")
    return max(0.0, min(abs(float(decision.reward)), 1.0))


def _diagnosis_metric_boundary(diagnosis: Diagnosis) -> tuple[str, float]:
    metric = _normalize_metric(str(diagnosis.evidence.get("metric", "")))
    threshold = diagnosis.evidence.get("threshold")
    if not metric or isinstance(threshold, bool) or not isinstance(
        threshold, (int, float)
    ):
        raise AutoGenDecisionError(
            "AutoGen diagnosis is missing metric or threshold context"
        )
    if not math.isfinite(float(threshold)):
        raise AutoGenDecisionError("AutoGen threshold must be finite")
    return metric, float(threshold)


def _recovery_action_from_decision(
    decision: AgentDecision,
    evidence: EvidenceSnapshot,
) -> RecoveryAction:
    parameters = decision.parameters
    namespace = parameters.get("namespace") or evidence.namespace
    deployment = parameters.get("deployment") or evidence.deployment
    if not decision.approved or decision.action == "app_observe_only":
        kind = RecoveryActionKind.OBSERVE_ONLY
        replicas = None
    elif decision.action == "app_rollout_restart":
        kind = RecoveryActionKind.ROLLOUT_RESTART
        replicas = None
    elif decision.action == "app_scale_deployment":
        replicas_text = parameters.get("replicas", "")
        if not replicas_text.isdecimal():
            raise AutoGenDecisionError(
                f"replicas must be an integer: {replicas_text or '<missing>'}"
            )
        kind = RecoveryActionKind.SCALE_OUT
        replicas = int(replicas_text)
    else:
        raise AutoGenDecisionError(
            f"unsupported AutoGen application action: {decision.action}"
        )
    return RecoveryAction(
        namespace=namespace,
        deployment=deployment,
        kind=kind,
        replicas=replicas,
        reason=decision.reason,
    )

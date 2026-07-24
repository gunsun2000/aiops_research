from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from aiops_k8s_agents.models import RecoveryAction


class ReviewVerdict(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    VETO = "veto"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class SupervisionDecision:
    decision_id: str
    run_id: str
    round_index: int
    agent: str
    decision_type: str
    proposed_action: RecoveryAction | None
    approved: bool
    reason: str
    confidence: float
    evidence_refs: tuple[str, ...]
    reward: float
    policy_version: str


@dataclass(frozen=True)
class PeerReview:
    review_id: str
    run_id: str
    round_index: int
    reviewer: str
    target_agent: str
    target_decision_id: str
    verdict: ReviewVerdict
    reason: str
    suggested_action: RecoveryAction | None
    confidence: float
    evidence_refs: tuple[str, ...]
    policy_version: str


@dataclass(frozen=True)
class NegotiationRound:
    run_id: str
    round_index: int
    input_decision_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    revisions: tuple[str, ...]
    remaining_vetoes: tuple[str, ...]
    remaining_abstentions: tuple[str, ...]
    consensus_status: str
    selected_action_id: str | None
    decision_scopes: tuple[str, ...] = ()
    consensus_strategy: str = ""
    non_blocking_objections: tuple[str, ...] = ()
    consensus_reason: str = ""


@dataclass(frozen=True)
class PostExecutionReview:
    review_id: str
    run_id: str
    agent: str
    action_id: str
    approved: bool
    reason: str
    confidence: float
    evidence_refs: tuple[str, ...]
    policy_version: str


def new_trace_id(prefix: str) -> str:
    normalized = prefix.strip().lower().replace("_", "-")
    if not normalized:
        raise ValueError("trace id prefix must not be empty")
    return f"{normalized}-{uuid4().hex}"


def to_serializable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_serializable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): to_serializable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [to_serializable(item) for item in value]
    return value

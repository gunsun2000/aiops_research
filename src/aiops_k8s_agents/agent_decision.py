from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentDecision:
    """Decision, action, and reward emitted by one research agent."""

    agent: str
    action: str
    reward: float
    approved: bool
    reason: str
    parameters: dict[str, str] = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class AlertEvent:
    namespace: str
    service: str
    metric: str
    value: float
    threshold: float
    message: str


@dataclass(frozen=True)
class Diagnosis:
    service: str
    cause: str
    severity: str
    confidence: float


@dataclass(frozen=True)
class ScaleAction:
    namespace: str
    deployment: str
    replicas: int
    reason: str


class RecoveryActionKind(str, Enum):
    OBSERVE_ONLY = "observe_only"
    ROLLOUT_RESTART = "rollout_restart"
    SCALE_OUT = "scale_out"


@dataclass(frozen=True)
class RecoveryAction:
    namespace: str
    deployment: str
    kind: RecoveryActionKind
    replicas: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class CommandResult:
    command: str
    mode: str
    valid: bool
    stdout: str
    stderr: str
    metadata: dict[str, str] = field(default_factory=dict)

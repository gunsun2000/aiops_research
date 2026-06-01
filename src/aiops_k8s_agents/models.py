from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class CommandResult:
    command: str
    mode: str
    valid: bool
    stdout: str
    stderr: str
    metadata: dict[str, str] = field(default_factory=dict)

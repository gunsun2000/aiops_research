from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from aiops_k8s_agents.experiment_session import ExperimentSession
from aiops_k8s_agents.executor import ExecutionBackend, ExecutionMode


class RuntimeStage(str, Enum):
    QUEUED = "queued"
    PREFLIGHT = "preflight"
    INJECTING_FAULT = "injecting_fault"
    COLLECTING_EVIDENCE = "collecting_evidence"
    AGENT_REASONING = "agent_reasoning"
    NEGOTIATING = "negotiating"
    VALIDATING = "validating"
    EXECUTING = "executing"
    OBSERVING_RECOVERY = "observing_recovery"
    ANALYZING = "analyzing"
    CLEANUP = "cleanup"
    COMPLETED = "completed"


@dataclass(frozen=True)
class CoordinatorRuntimeCapabilities:
    """Safety contract required before a coordinator may receive a fault."""

    bounded: bool = True
    cancellable: bool = True
    finite_stage_io: bool = True
    deadline_aware: bool = True


@dataclass(frozen=True)
class ExperimentRuntimeRequest:
    scenario_id: str
    namespace: str
    deployment: str
    metric: str
    threshold: float
    mode: ExecutionMode
    backend: ExecutionBackend
    protocol_profile: str
    repetitions: int = 1

    def __post_init__(self) -> None:
        for name in (
            "scenario_id",
            "namespace",
            "deployment",
            "protocol_profile",
        ):
            value = _strip_identifier(name, getattr(self, name))
            object.__setattr__(self, name, value)

        metric = _strip_identifier("metric", self.metric)
        object.__setattr__(self, "metric", metric.lower().replace("-", "_"))
        object.__setattr__(self, "mode", _enum_value(ExecutionMode, self.mode))
        object.__setattr__(self, "backend", _enum_value(ExecutionBackend, self.backend))

        if isinstance(self.repetitions, bool) or not isinstance(self.repetitions, int):
            raise ValueError("repetitions must be an integer >= 1")
        if self.repetitions < 1:
            raise ValueError("repetitions must be an integer >= 1")
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float)):
            raise ValueError("threshold must be finite")
        if not isfinite(self.threshold):
            raise ValueError("threshold must be finite")
        object.__setattr__(self, "threshold", float(self.threshold))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe({
            "scenario_id": self.scenario_id,
            "namespace": self.namespace,
            "deployment": self.deployment,
            "metric": self.metric,
            "threshold": self.threshold,
            "mode": self.mode.value,
            "backend": self.backend.value,
            "protocol_profile": self.protocol_profile,
            "repetitions": self.repetitions,
        })


@dataclass(frozen=True)
class RuntimeEvent:
    experiment_id: str
    sequence: int
    stage: RuntimeStage
    status: str
    message: str
    created_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        experiment_id = _strip_identifier("experiment_id", self.experiment_id)
        status = _strip_identifier("status", self.status)
        message = _strip_identifier("message", self.message)
        created_at = _strip_identifier("created_at", self.created_at)
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise ValueError("sequence must be non-negative")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        object.__setattr__(self, "experiment_id", experiment_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "stage", _enum_value(RuntimeStage, self.stage))
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        object.__setattr__(self, "payload", _freeze(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe({
            "experiment_id": self.experiment_id,
            "sequence": self.sequence,
            "stage": self.stage.value,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
            "payload": self.payload,
        })


@dataclass(frozen=True)
class ExperimentRuntimeResult:
    experiment_id: str
    status: str
    report: Mapping[str, Any]
    session: ExperimentSession
    events: tuple[RuntimeEvent, ...]
    cleanup: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment_id", _strip_identifier("experiment_id", self.experiment_id))
        object.__setattr__(self, "status", _strip_identifier("status", self.status))
        if not isinstance(self.report, Mapping):
            raise TypeError("report must be a mapping")
        if not isinstance(self.cleanup, Mapping):
            raise TypeError("cleanup must be a mapping")
        if not isinstance(self.session, ExperimentSession):
            raise TypeError("session must be an ExperimentSession")
        _json_safe(self.session.to_dict())
        events = tuple(self.events)
        if not all(isinstance(event, RuntimeEvent) for event in events):
            raise TypeError("events must contain RuntimeEvent values")
        object.__setattr__(self, "report", _freeze(self.report))
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "cleanup", _freeze(self.cleanup))

    def to_dict(self) -> dict[str, Any]:
        return _json_safe({
            "experiment_id": self.experiment_id,
            "status": self.status,
            "report": self.report,
            "session": self.session.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "cleanup": self.cleanup,
        })


def _strip_identifier(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _enum_value(enum_type: type[Enum], value: Any) -> Enum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {enum_type.__name__}: {value!r}") from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, Enum):
        return _freeze(value.value)
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("float values must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return deepcopy(value)
    raise TypeError(
        f"value of type {type(value).__name__} is not JSON serializable"
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]
    if isinstance(value, frozenset | set):
        return [_json_safe(item) for item in sorted(value, key=repr)]
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("float values must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(
        f"value of type {type(value).__name__} is not JSON serializable"
    )
